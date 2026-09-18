import os, termios, time, select, sys, subprocess
fd = os.open("/dev/cu.usbserial-AR7QY85A", os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
a = termios.tcgetattr(fd)
a[0]=0; a[1]=0; a[2]=termios.CS8|termios.CREAD|termios.CLOCAL; a[3]=0; a[4]=a[5]=termios.B9600
termios.tcsetattr(fd, termios.TCSANOW, a); termios.tcflush(fd, termios.TCIOFLUSH)
def cmd(c):
    os.write(fd, (":"+c+"\r").encode()); out=b""; t=time.time()+1.5
    while time.time()<t and not out.endswith(b"\r"):
        r,_,_=select.select([fd],[],[],0.02)
        if r:
            try: out+=os.read(fd,256)
            except BlockingIOError: pass
    s=out.decode(errors="replace").strip()
    if not s.startswith("="): raise RuntimeError(f":{c} -> {s!r}")
    return s
def val(s): h=s[1:]; return int("".join(h[i:i+2] for i in range(len(h)-2,-1,-2)),16)
def enc(n): h=f"{n:06X}"; return h[4:6]+h[2:4]+h[0:2]
def say(t): print("\n>>", t, flush=True); subprocess.run(["say", t])
def pos(): return val(cmd("j1"))
def running(): return int(cmd("f1")[2],16)&1

cmd("F1"); cmd("F2")
CPR=val(cmd("a1")); TF=val(cmd("b1")); HS=val(cmd("g1"))
SID=CPR/86164.0905          # steps/s at sidereal
DEG=CPR/360
P0=pos(); FENCE=4.0
def off(): return (pos()-P0)/DEG
def halt(): 
    try: cmd("K1"); cmd("K2")
    finally: pass
def guard_wait(timeout=30):
    t=time.time()
    while running():
        o=off()
        if abs(o)>FENCE:
            cmd("L1"); halt(); raise SystemExit(f"FENCE HIT at {o:+.2f} deg, stopped")
        if time.time()-t>timeout: halt(); raise SystemExit("timeout")
        time.sleep(0.05)
def stop_and_wait():
    cmd("K1"); guard_wait()
def goto_home():
    d=pos()-P0
    if d==0: return
    cmd("K1"); guard_wait()
    cmd("G10"+("1" if d>0 else "0")); cmd("H1"+enc(abs(d))); cmd("M1"+enc(min(3500,abs(d)//2))); cmd("J1"); guard_wait()
def run_rate(rate, secs, direction=0):
    """constant-speed run; returns measured steps/s during steady portion"""
    fast = rate>128
    I = round(TF*(HS if fast else 1)*86164.0905/(CPR*rate))
    cmd("K1"); guard_wait()
    cmd(f"G1{'3' if fast else '1'}{direction}"); cmd("I1"+enc(I)); cmd("J1")
    t_start=time.time(); samples=[]
    settle = 0.6 if fast else 0.3
    while time.time()-t_start<secs:
        o=off()
        if abs(o)>FENCE: cmd("L1"); halt(); raise SystemExit(f"FENCE HIT at {o:+.2f} deg")
        if time.time()-t_start>settle: samples.append((time.time(), pos()))
        time.sleep(0.05)
    stop_and_wait()
    (t0,p0),(t1,p1)=samples[0],samples[-1]
    return abs(p1-p0)/(t1-t0), I

try:
    print(f"CPR={CPR} timer={TF} hs={HS} sidereal={SID:.3f} steps/s  start pos={P0}")
    # ---- 1. sidereal tracking
    say("Test one. Sidereal tracking on R A for sixty seconds.")
    I=round(TF*86164.0905/CPR)
    cmd("G110"); cmd("I1"+enc(I)); p_a=pos(); t_a=time.time(); cmd("J1")
    time.sleep(1); p_a=pos(); t_a=time.time()
    time.sleep(60)
    p_b=pos(); t_b=time.time(); stop_and_wait()
    r=(p_b-p_a)/(t_b-t_a)
    nominal=TF/I
    print(f"tracking: measured {r:.3f} steps/s, commanded {nominal:.3f}, ideal {SID:.3f}")
    print(f"  -> commanded vs ideal error {(nominal/SID-1)*100:+.3f}%  ({(nominal-SID)/DEG*3600*60:+.2f} arcsec/min)")
    print(f"  -> measured vs ideal       {(r/SID-1)*100:+.3f}%  (moved {(p_b-p_a)/DEG*3600:.0f} arcsec in {t_b-t_a:.1f}s)")
    goto_home()
    # ---- 2. speed ladder, alternating direction, returning home each time
    say("Test two. Speed ladder on R A. Each run returns to start.")
    for rate, secs in ((8,5),(64,4),(400,1.8),(800,1.4)):
        say(f"{rate} times sidereal")
        meas, I = run_rate(rate, secs)
        print(f"  {rate:>4}x: I={I}  measured {meas:9.1f} steps/s = {meas/SID:6.1f}x = {meas/DEG:.3f} deg/s   peak offset {off():+.2f} deg")
        goto_home()
    # ---- 3. stop test
    say("Test three. Stop mid slew.")
    cmd("K1"); guard_wait()
    target=round(3.5*DEG)
    cmd("G100"); cmd("H1"+enc(target)); cmd("M1"+enc(3500)); cmd("J1")
    time.sleep(0.6)
    o_cmd=off(); t_k=time.time(); cmd("K1")
    while running(): time.sleep(0.01)
    dt=time.time()-t_k; o_stop=off()
    print(f"stop: K sent at {o_cmd:+.2f} deg, stopped at {o_stop:+.2f} deg after {dt:.2f}s (coasted {o_stop-o_cmd:.2f} deg; goto target was +3.50)")
    goto_home()
    print(f"final offset {off():+.4f} deg")
    say("All tests done. R A is back where it started.")
except BaseException:
    halt(); raise
