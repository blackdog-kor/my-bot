from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.start()


def list_jobs():
    return scheduler.get_jobs()


def remove_job(job_id: str) -> bool:
    try:
        scheduler.remove_job(job_id)
        return True
    except Exception:
        return False
