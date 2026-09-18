DEG=10
import os, termios, time, select, sys, subprocess
fd = os.open("/dev/cu.usbserial-AR7QY85A", os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
a = termios.tcgetattr(fd)
a[0]=0; a[1]=0; a[2]=termios.CS8|termios.CREAD|termios.CLOCAL; a[3]=0; a[4]=a[5]=termios.B9600
termios.tcsetattr(fd, termios.TCSANOW, a); termios.tcflush(fd, termios.TCIOFLUSH)
def cmd(c, quiet=False):
    os.write(fd, (":"+c+"\r").encode()); out=b""; t=time.time()+1.5
    while time.time()<t and not out.endswith(b"\r"):
        r,_,_=select.select([fd],[],[],0.05)
        if r:
            try: out+=os.read(fd,256)
            except BlockingIOError: pass
    s=out.decode(errors="replace").strip()
    if not quiet: print(f"  :{c:<10} -> {s!r}", flush=True)
    return s
def val(s): h=s[1:]; return int("".join(h[i:i+2] for i in range(len(h)-2,-1,-2)),16)
def enc(n): h=f"{n:06X}"; return h[4:6]+h[2:4]+h[0:2]
def say(t): print(">>", t, flush=True); subprocess.run(["say", t])
def running(ax):
    s=cmd(f"f{ax}", quiet=True); return len(s)>2 and int(s[2],16)&1
def stop_all(): cmd("K1"); cmd("K2")

try:
    if not cmd("e1").startswith("="): sys.exit("no response")
    cmd("F1"); cmd("F2")
    names={1:"R A", 2:"declination"}
    for ax in (1,2):
        cpr=val(cmd(f"a{ax}")); steps=round(cpr*DEG/360)
        p0=val(cmd(f"j{ax}"))
        for label, dirbit in (("forward",0),("back",1)):
            say(f"Moving {names[ax]} {label} ten degrees")
            cmd(f"K{ax}")
            while running(ax): time.sleep(0.1)
            cmd(f"G{ax}0{dirbit}")          # goto mode, direction
            cmd(f"H{ax}{enc(steps)}")       # relative distance
            cmd(f"M{ax}{enc(min(3500, steps//2))}")  # brake point
            cmd(f"J{ax}")
            t=time.time(); t0=t
            while running(ax):
                if time.time()-t>30: stop_all(); sys.exit("timeout, stopped")
                time.sleep(0.2)
            p=val(cmd(f"j{ax}"))
            print(f"  {names[ax]} {label}: pos {p}, offset from start {(p-p0)*360/cpr:+.2f} deg, took {time.time()-t0:.1f}s", flush=True)
            time.sleep(1)
    say("Done. Both axes tested.")
except BaseException as e:
    stop_all(); raise
