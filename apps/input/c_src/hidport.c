/* hidport: tiny bridge between libhidapi and an Erlang port.
 *
 *   hidport list                 -> one line per HID device:
 *                                    L <vid> <pid> <usage_page> <usage> <path> \t <manufacturer> \t <product>
 *   hidport open <path>          -> streams input reports as  R <hex bytes>
 *                                   until stdin closes (the VM went away) or the device does.
 * Everything else is Elixir's job. */
#include <hidapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wchar.h>
#include <sys/select.h>

static void wprint(const wchar_t *w) {
  if (!w) return;
  char buf[256]; size_t n = wcstombs(buf, w, sizeof(buf) - 1);
  if (n == (size_t)-1) n = 0; buf[n] = 0;
  for (char *c = buf; *c; c++) if (*c == '\t' || *c == '\n') *c = ' ';
  fputs(buf, stdout);
}

static int list(void) {
  struct hid_device_info *devs = hid_enumerate(0, 0), *d;
  for (d = devs; d; d = d->next) {
    printf("L %04x %04x %04x %04x %s\t", d->vendor_id, d->product_id, d->usage_page, d->usage, d->path);
    wprint(d->manufacturer_string); fputs("\t", stdout); wprint(d->product_string); fputs("\n", stdout);
  }
  hid_free_enumeration(devs);
  fflush(stdout);
  return 0;
}

static int stdin_closed(void) {
  fd_set fds; struct timeval tv = {0, 0};
  FD_ZERO(&fds); FD_SET(0, &fds);
  if (select(1, &fds, NULL, NULL, &tv) > 0) { char c; return read(0, &c, 1) <= 0; }
  return 0;
}

static int stream(const char *path) {
  hid_device *h = hid_open_path(path);
  if (!h) { fprintf(stdout, "E cannot open %s\n", path); fflush(stdout); return 2; }
  hid_set_nonblocking(h, 0);
  unsigned char buf[64];
  printf("O %s\n", path); fflush(stdout);
  for (;;) {
    int n = hid_read_timeout(h, buf, sizeof buf, 50);
    if (n < 0) { fputs("E read failed\n", stdout); fflush(stdout); break; }
    if (n > 0) {
      fputs("R ", stdout);
      for (int i = 0; i < n; i++) printf("%02x", buf[i]);
      fputs("\n", stdout); fflush(stdout);
    }
    if (stdin_closed()) break;
  }
  hid_close(h);
  return 0;
}

int main(int argc, char **argv) {
  setvbuf(stdout, NULL, _IOLBF, 0);
  if (hid_init() != 0) { fputs("E hid_init failed\n", stdout); return 1; }
  int rc = 1;
  if (argc >= 2 && strcmp(argv[1], "list") == 0) rc = list();
  else if (argc >= 3 && strcmp(argv[1], "open") == 0) rc = stream(argv[2]);
  else fputs("usage: hidport list | hidport open <path>\n", stderr);
  hid_exit();
  return rc;
}
