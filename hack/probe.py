import os, termios, time, select, sys
fd = os.open("/dev/cu.usbserial-AR7QY85A", os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
a = termios.tcgetattr(fd)
a[0]=0; a[1]=0; a[2]=termios.CS8|termios.CREAD|termios.CLOCAL; a[3]=0; a[4]=a[5]=termios.B9600
termios.tcsetattr(fd, termios.TCSANOW, a); termios.tcflush(fd, termios.TCIOFLUSH)
def cmd(c):
    os.write(fd, (":"+c+"\r").encode()); out=b""; t=time.time()+1.0
    while time.time()<t and not out.endswith(b"\r"):
        r,_,_=select.select([fd],[],[],0.05)
        if r:
            try: out+=os.read(fd,256)
            except BlockingIOError: pass
    s=out.decode(errors="replace").strip()
    print(f":{c:<10} -> {s!r}", flush=True); return s
def val(s):  # little-endian hex bytes -> int
    h=s[1:]; return int("".join(h[i:i+2] for i in range(len(h)-2,-1,-2)),16)
def enc(n): h=f"{n:06X}"; return h[4:6]+h[2:4]+h[0:2]
v=cmd("e1")
if not v.startswith("="): sys.exit("no response from mount")
cpr=val(cmd("a1")); tf=val(cmd("b1")); hs=val(cmd("g1"))
print(f"RA steps/rev={cpr} timer={tf} highspeed_ratio={hs}")
cmd("f1"); cmd("F3")
p0=val(cmd("j1"))
if "--slew" not in sys.argv: sys.exit()
R=200  # x sidereal, fast mode  (~0.84 deg/s)
I=round(tf*hs*86164.09/(cpr*R))
cmd("K1"); time.sleep(0.3)
cmd("G130"); cmd("I1"+enc(I)); cmd("J1")
time.sleep(4)
cmd("K1")
for _ in range(30):
    s=cmd("f1")
    if len(s)>2 and not (int(s[2],16)&1): break
    time.sleep(0.2)
p1=val(cmd("j1"))
print(f"moved {p1-p0} steps = {(p1-p0)*360/cpr:.2f} deg")
