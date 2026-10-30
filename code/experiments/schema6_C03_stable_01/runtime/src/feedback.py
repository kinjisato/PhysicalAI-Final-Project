"""Read a settled measured endpoint; never change goals, paths or safety limits."""
import math,time

def settled_current(node,timeout=6.0,window=.25,max_span=.0005,clock=time.monotonic):
    started=clock();history=[];count=0;first=None;last_stamp=None
    while True:
        remaining=timeout-(clock()-started)
        if remaining<=0:raise RuntimeError('No fresh settled joint feedback within measurement deadline')
        q=node.current(timeout=remaining)
        if not q or any(not math.isfinite(v) for v in q.values()):raise RuntimeError('Nonfinite joint feedback')
        msg=node.js;stamp=msg.header.stamp.sec+msg.header.stamp.nanosec/1e9
        if not math.isfinite(stamp):raise RuntimeError('Nonfinite joint feedback timestamp')
        if last_stamp is not None and stamp<last_stamp:raise RuntimeError('Joint feedback clock moved backwards')
        if last_stamp is not None and stamp==last_stamp:continue
        last_stamp=stamp;count+=1
        if first is None:first={'stamp':stamp,'joint_rad':dict(q)}
        history.append((stamp,dict(q)))
        # Keep one sample at/before the complete simulation-time observation window.
        while len(history)>2 and history[1][0]<=stamp-window:history.pop(0)
        elapsed=clock()-started;span=max(max(x[n] for _,x in history)-min(x[n] for _,x in history) for n in q)
        if elapsed>=window and len(history)>=3 and stamp-history[0][0]>=window and span<=max_span:
            return dict(q),{'measurement':'fresh_settled_joint_feedback','wall_seconds':elapsed,'unique_samples':count,'first_observation':first,'last_stamp':stamp,'settled_sim_seconds':stamp-history[0][0],'max_joint_span_rad':span,'required_window_seconds':window,'required_max_span_rad':max_span}
