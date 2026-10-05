/*
 * usbport: the thin edge between Elixir and a USB camera. It only moves bytes:
 * open one device's still-image interface, then bulk writes and reads (and
 * interrupt reads for events) on request. Everything that knows what the bytes
 * mean (PTP, Sony's extensions) is Elixir (Camera.Ptp, Camera.Sony).
 *
 * Linux (the box): the kernel's usbfs, no library. macOS: libusb.
 *
 *   usbport list                 one line per still-image device (macOS; Linux reads sysfs from Elixir)
 *       D <bus>:<addr> <vid> <pid> <iface>\t<manufacturer>\t<product>
 *   usbport open <device> [iface]  then {packet, 4} frames on stdin/stdout:
 *       first reply:  'O' bulk_in bulk_out int_in max_packet(u16 LE)
 *       'W' ep timeout(u32 LE) data   -> 'w' status(i32 LE)          bulk write (+ zero-length packet when data fills whole packets)
 *       'R' ep timeout(u32 LE) max(u32 LE) -> 'r' status(i32 LE) data  bulk read, one transfer
 *       'I' ep timeout(u32 LE) max(u32 LE) -> 'i' status(i32 LE) data  interrupt read (events)
 *       'C' ep                        -> 'c' status(i32 LE)          clear a stalled endpoint
 *   status is bytes moved (>= 0) or -errno. On Linux <device> is /dev/bus/usb/BBB/DDD;
 *   on macOS it is bus:address, as `list` prints it.
 */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MAX_READ (4 * 1024 * 1024)

static int read_full(int fd, void *buf, size_t n) {
  size_t got = 0;
  while (got < n) {
    ssize_t r = read(fd, (char *)buf + got, n - got);
    if (r <= 0) {
      if (r < 0 && errno == EINTR) continue;
      return -1;
    }
    got += (size_t)r;
  }
  return 0;
}

static int write_full(int fd, const void *buf, size_t n) {
  size_t put = 0;
  while (put < n) {
    ssize_t r = write(fd, (const char *)buf + put, n - put);
    if (r <= 0) {
      if (r < 0 && errno == EINTR) continue;
      return -1;
    }
    put += (size_t)r;
  }
  return 0;
}

static void put32(unsigned char *p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }
static uint32_t get32(const unsigned char *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }

/* one {packet, 4} frame out: 4-byte big-endian length, then the bytes */
static void reply(const unsigned char *head, size_t hn, const unsigned char *body, size_t bn) {
  unsigned char len[4];
  uint32_t n = (uint32_t)(hn + bn);
  len[0] = n >> 24; len[1] = n >> 16; len[2] = n >> 8; len[3] = n;
  if (write_full(1, len, 4) || write_full(1, head, hn) || (bn && write_full(1, body, bn))) exit(3);
}

static void reply_status(char tag, int32_t status, const unsigned char *body, size_t bn) {
  unsigned char head[5];
  head[0] = tag;
  put32(head + 1, (uint32_t)status);
  reply(head, 5, body, bn);
}

/* the endpoints of a still-image interface */
struct eps { int iface, bulk_in, bulk_out, int_in, max_packet; };

/* walk a configuration descriptor: the interface (class 6, or the one asked for) and its endpoints */
static int find_eps(const unsigned char *d, int n, int want_iface, struct eps *e) {
  int i = 0, cur = -1, found = 0;
  memset(e, 0, sizeof(*e));
  e->iface = -1;
  while (i + 2 <= n) {
    int len = d[i], type = d[i + 1];
    if (len < 2 || i + len > n) break;
    if (type == 4 && len >= 9) { /* interface */
      int num = d[i + 2], cls = d[i + 5];
      cur = (want_iface >= 0) ? (num == want_iface ? num : -1) : (cls == 6 ? num : -1);
      if (cur >= 0 && !found) { e->iface = num; found = 1; } else if (found && num != e->iface) cur = -1;
    } else if (type == 5 && len >= 7 && cur >= 0 && cur == e->iface) { /* endpoint */
      int addr = d[i + 2], attr = d[i + 3] & 3, mp = d[i + 4] | (d[i + 5] << 8);
      if (attr == 2 && (addr & 0x80)) { e->bulk_in = addr; e->max_packet = mp; }
      else if (attr == 2) e->bulk_out = addr;
      else if (attr == 3 && (addr & 0x80)) e->int_in = addr;
    }
    i += len;
  }
  return (e->iface >= 0 && e->bulk_in && e->bulk_out) ? 0 : -1;
}

/* -- the two backends: open, bulk, interrupt, clear halt -------------------------------------- */

#if defined(__linux__)
#include <linux/usbdevice_fs.h>
#include <sys/ioctl.h>

static int fd = -1;

static int dev_open(const char *path, int want_iface, struct eps *e) {
  unsigned char desc[4096];
  int n;
  fd = open(path, O_RDWR);
  if (fd < 0) return -errno;
  /* reading the device node gives the device descriptor, then the active configuration */
  n = (int)read(fd, desc, sizeof desc);
  if (n < 18) return -EIO;
  if (find_eps(desc + 18, n - 18, want_iface, e)) return -ENODEV;
  {
    /* a kernel driver (usb-storage in the camera's other modes) lets go first; none is fine */
    struct usbdevfs_ioctl cmd = { .ifno = e->iface, .ioctl_code = USBDEVFS_DISCONNECT, .data = NULL };
    ioctl(fd, USBDEVFS_IOCTL, &cmd);
  }
  if (ioctl(fd, USBDEVFS_CLAIMINTERFACE, &e->iface) < 0) return -errno;
  return 0;
}

static int xfer(int ep, unsigned char *buf, int len, unsigned int timeout) {
  struct usbdevfs_bulktransfer bt = { .ep = (unsigned int)ep, .len = (unsigned int)len, .timeout = timeout, .data = buf };
  int r = ioctl(fd, USBDEVFS_BULK, &bt); /* interrupt endpoints go through the same call */
  return r < 0 ? -errno : r;
}

static int bulk(int ep, unsigned char *buf, int len, unsigned int timeout) { return xfer(ep, buf, len, timeout); }
static int intr(int ep, unsigned char *buf, int len, unsigned int timeout) { return xfer(ep, buf, len, timeout); }

static int clear_halt(int ep) {
  unsigned int e = (unsigned int)ep;
  return ioctl(fd, USBDEVFS_CLEAR_HALT, &e) < 0 ? -errno : 0;
}

static int list(void) { return 0; /* Linux: Elixir reads /sys/bus/usb/devices itself */ }

#elif defined(HAVE_LIBUSB)
#include <libusb.h>

static libusb_device_handle *h = NULL;

static int lerr(int r) {
  switch (r) {
    case LIBUSB_ERROR_TIMEOUT: return -ETIMEDOUT;
    case LIBUSB_ERROR_NO_DEVICE: return -ENODEV;
    case LIBUSB_ERROR_PIPE: return -EPIPE;
    case LIBUSB_ERROR_BUSY: return -EBUSY;
    case LIBUSB_ERROR_ACCESS: return -EACCES;
    case LIBUSB_ERROR_OVERFLOW: return -EOVERFLOW;
    default: return -EIO;
  }
}

static int dev_open(const char *spec, int want_iface, struct eps *e) {
  int bus, addr, r;
  libusb_device **list;
  ssize_t cnt;
  if (sscanf(spec, "%d:%d", &bus, &addr) != 2) return -EINVAL;
  if (libusb_init(NULL)) return -EIO;
  cnt = libusb_get_device_list(NULL, &list);
  for (ssize_t i = 0; i < cnt; i++) {
    libusb_device *d = list[i];
    struct libusb_config_descriptor *cfg;
    if (libusb_get_bus_number(d) != bus || libusb_get_device_address(d) != addr) continue;
    if (libusb_get_active_config_descriptor(d, &cfg) == 0) {
      /* the raw bytes of the configuration, walked the same way as on Linux */
      unsigned char raw[4096];
      int n = 0;
      memcpy(raw, cfg, 0); /* libusb parses for us; rebuild what find_eps needs */
      for (int k = 0; k < cfg->bNumInterfaces; k++) {
        const struct libusb_interface_descriptor *id = &cfg->interface[k].altsetting[0];
        if (n + 9 > (int)sizeof raw) break;
        raw[n] = 9; raw[n + 1] = 4; raw[n + 2] = id->bInterfaceNumber; raw[n + 5] = id->bInterfaceClass; n += 9;
        for (int j = 0; j < id->bNumEndpoints && n + 7 <= (int)sizeof raw; j++) {
          const struct libusb_endpoint_descriptor *ep = &id->endpoint[j];
          raw[n] = 7; raw[n + 1] = 5; raw[n + 2] = ep->bEndpointAddress; raw[n + 3] = ep->bmAttributes;
          raw[n + 4] = ep->wMaxPacketSize & 0xff; raw[n + 5] = ep->wMaxPacketSize >> 8; n += 7;
        }
      }
      libusb_free_config_descriptor(cfg);
      if (find_eps(raw, n, want_iface, e)) { libusb_free_device_list(list, 1); return -ENODEV; }
    }
    r = libusb_open(d, &h);
    libusb_free_device_list(list, 1);
    if (r) return lerr(r);
    libusb_set_auto_detach_kernel_driver(h, 1);
    r = libusb_claim_interface(h, e->iface);
    return r ? lerr(r) : 0;
  }
  libusb_free_device_list(list, 1);
  return -ENODEV;
}

static int bulk(int ep, unsigned char *buf, int len, unsigned int timeout) {
  int moved = 0, r = libusb_bulk_transfer(h, (unsigned char)ep, buf, len, &moved, timeout);
  return (r && !(r == LIBUSB_ERROR_TIMEOUT && moved > 0)) ? lerr(r) : moved;
}

static int intr(int ep, unsigned char *buf, int len, unsigned int timeout) {
  int moved = 0, r = libusb_interrupt_transfer(h, (unsigned char)ep, buf, len, &moved, timeout);
  return r ? lerr(r) : moved;
}

static int clear_halt(int ep) { return lerr(libusb_clear_halt(h, (unsigned char)ep)); }

static int list(void) {
  libusb_device **devs;
  ssize_t cnt;
  if (libusb_init(NULL)) return 1;
  cnt = libusb_get_device_list(NULL, &devs);
  for (ssize_t i = 0; i < cnt; i++) {
    struct libusb_device_descriptor dd;
    struct libusb_config_descriptor *cfg;
    int iface = -1;
    if (libusb_get_device_descriptor(devs[i], &dd) || libusb_get_active_config_descriptor(devs[i], &cfg)) continue;
    for (int k = 0; k < cfg->bNumInterfaces && iface < 0; k++)
      if (cfg->interface[k].altsetting[0].bInterfaceClass == 6) iface = cfg->interface[k].altsetting[0].bInterfaceNumber;
    libusb_free_config_descriptor(cfg);
    if (iface < 0) continue;
    {
      char man[128] = "", prod[128] = "";
      libusb_device_handle *dh;
      if (libusb_open(devs[i], &dh) == 0) {
        if (dd.iManufacturer) libusb_get_string_descriptor_ascii(dh, dd.iManufacturer, (unsigned char *)man, sizeof man);
        if (dd.iProduct) libusb_get_string_descriptor_ascii(dh, dd.iProduct, (unsigned char *)prod, sizeof prod);
        libusb_close(dh);
      }
      printf("D %d:%d %04x %04x %d\t%s\t%s\n", libusb_get_bus_number(devs[i]), libusb_get_device_address(devs[i]),
             dd.idVendor, dd.idProduct, iface, man, prod);
    }
  }
  libusb_free_device_list(devs, 1);
  return 0;
}

#else
static int dev_open(const char *p, int w, struct eps *e) { (void)p; (void)w; (void)e; return -ENOSYS; }
static int bulk(int ep, unsigned char *b, int l, unsigned int t) { (void)ep; (void)b; (void)l; (void)t; return -ENOSYS; }
static int intr(int ep, unsigned char *b, int l, unsigned int t) { (void)ep; (void)b; (void)l; (void)t; return -ENOSYS; }
static int clear_halt(int ep) { (void)ep; return -ENOSYS; }
static int list(void) { return 0; }
#endif

/* -- the request loop -------------------------------------------------------------------------- */

static int serve(const char *device, int want_iface) {
  struct eps e;
  unsigned char hello[6];
  static unsigned char buf[MAX_READ];
  int r = dev_open(device, want_iface, &e);
  if (r < 0) {
    reply_status('E', r, NULL, 0);
    return 1;
  }
  hello[0] = 'O'; hello[1] = (unsigned char)e.bulk_in; hello[2] = (unsigned char)e.bulk_out; hello[3] = (unsigned char)e.int_in;
  hello[4] = e.max_packet & 0xff; hello[5] = e.max_packet >> 8;
  reply(hello, 6, NULL, 0);

  for (;;) {
    unsigned char lenb[4], *req;
    uint32_t n;
    if (read_full(0, lenb, 4)) return 0; /* the port closed: the owner is done */
    n = ((uint32_t)lenb[0] << 24) | (lenb[1] << 16) | (lenb[2] << 8) | lenb[3];
    if (n < 2 || n > MAX_READ + 16) return 2;
    req = malloc(n);
    if (!req || read_full(0, req, n)) return 2;

    switch (req[0]) {
      case 'W': {
        int ep = req[1], len = (int)n - 6;
        unsigned int timeout = get32(req + 2);
        int moved = 0;
        r = 0;
        while (moved < len && r >= 0) {
          r = bulk(ep, req + 6 + moved, len - moved, timeout);
          if (r > 0) moved += r; else if (r == 0) break;
        }
        /* a transfer that fills its last packet exactly ends with a zero-length one */
        if (r >= 0 && len > 0 && e.max_packet > 0 && len % e.max_packet == 0) r = bulk(ep, req, 0, timeout);
        reply_status('w', r < 0 ? r : moved, NULL, 0);
        break;
      }
      case 'R':
      case 'I': {
        int ep = req[1];
        unsigned int timeout = get32(req + 2);
        uint32_t max = get32(req + 6);
        if (max > MAX_READ) max = MAX_READ;
        r = req[0] == 'R' ? bulk(ep, buf, (int)max, timeout) : intr(ep, buf, (int)max, timeout);
        reply_status(req[0] == 'R' ? 'r' : 'i', r, buf, r > 0 ? (size_t)r : 0);
        break;
      }
      case 'C':
        reply_status('c', clear_halt(req[1]), NULL, 0);
        break;
      default:
        reply_status('?', -EINVAL, NULL, 0);
    }
    free(req);
  }
}

int main(int argc, char **argv) {
  if (argc >= 2 && !strcmp(argv[1], "list")) return list();
  if (argc >= 3 && !strcmp(argv[1], "open")) return serve(argv[2], argc >= 4 ? atoi(argv[3]) : -1);
  fprintf(stderr, "usage: usbport list | usbport open <device> [interface]\n");
  return 64;
}
