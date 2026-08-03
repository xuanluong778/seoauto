import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run_job_payload(job_id: str, payload: dict) -> None:
    from app.services.cluster_job_runner import run_cluster_job

    run_cluster_job(job_id, payload)


def main() -> None:
    from app.services.job_store import (
        claim_next_pending_job,
        ensure_job_schema,
        mark_stale_jobs_failed,
        update_job,
        fail_job,
    )

    ensure_job_schema()

    poll = float(os.getenv("JOB_WORKER_POLL_SECONDS", "1.2"))
    watchdog = int(os.getenv("JOB_WATCHDOG_SECONDS", "300"))
    hard_timeout = int(os.getenv("JOB_TOTAL_HARD_TIMEOUT", "420"))  # hard kill per job

    print("keyword_cluster_worker: started", flush=True)
    while True:
        try:
            mark_stale_jobs_failed(stale_seconds=watchdog)
            job = claim_next_pending_job(job_type="keyword_cluster")
            if not job:
                time.sleep(poll)
                continue

            payload = job.payload or {}
            update_job(job.job_id, state="RUNNING", progress=max(1, job.progress), message="Starting worker")

            # Hard timeout via subprocess.
            import multiprocessing as mp

            # Must NOT be daemon: clustering uses ProcessPoolExecutor internally.
            p = mp.Process(target=_run_job_payload, args=(job.job_id, payload), daemon=False)
            p.start()
            t0 = time.time()
            while p.is_alive():
                if time.time() - t0 > hard_timeout:
                    try:
                        p.terminate()
                    except Exception:
                        pass
                    fail_job(job.job_id, error=f"Hard timeout >{hard_timeout}s (worker killed process)")
                    break
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("keyword_cluster_worker: stop", flush=True)
            return
        except Exception as exc:
            # Avoid worker crash loop; sleep a bit.
            print(f"keyword_cluster_worker: error: {exc}", flush=True)
            time.sleep(2.0)


if __name__ == "__main__":
    main()

