import os
import time


def big(n):
    """A result bigger than the OS pipe buffer."""
    return "x" * n


def sleep_for(s):
    import time
    time.sleep(s)
    return s


def cell(x):
    """run_pool job: 'die' kills its worker, 'boom' raises, 'hang'
    never returns, an int doubles."""
    import os
    import time
    if x == "die":
        os._exit(3)
    if x == "boom":
        raise ValueError("bad cell")
    if x == "hang":
        time.sleep(3600)
    return 2 * x


def quick(x):
    return x * 2


def hang():
    time.sleep(600)


def boom():
    raise ValueError("injected fault")


def die():
    os._exit(9)


def progress_then_stall(n_moves):
    """Moves n_moves times, then sits still (alive, heartbeat-able,
    inside its timeout) - the 'slow wrong step'."""
    import time
    from brain_core.guards.watchdog import report_progress
    for k in range(n_moves):
        report_progress(k)
        time.sleep(0.3)
    time.sleep(3600)


def keeps_moving(n):
    import time
    from brain_core.guards.watchdog import report_progress
    for k in range(n):
        report_progress(k)
        time.sleep(0.3)
    return n
