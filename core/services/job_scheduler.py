# core/services/job_scheduler.py

import threading

JOB_RUNNING = False
JOB_QUEUE = []   # list of (job_id, callback_fn)


def schedule_job(job_id, callback):
    global JOB_RUNNING
    JOB_QUEUE.append((job_id, callback))

    if not JOB_RUNNING:
        _run_next_job()


def _run_next_job():
    global JOB_RUNNING

    if not JOB_QUEUE:
        JOB_RUNNING = False
        return

    JOB_RUNNING = True
    job_id, callback = JOB_QUEUE[0]

    thread = threading.Thread(target=_execute_job, args=(job_id, callback))
    thread.start()


def _execute_job(job_id, callback):
    global JOB_RUNNING, JOB_QUEUE

    try:
        callback(job_id)
    except Exception as e:
        print(f"Job {job_id} failed:", e)

    JOB_QUEUE.pop(0)
    _run_next_job()
