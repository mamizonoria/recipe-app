import threading
import time


def post_fork(server, worker):
    """各workerでDB接続を3分おきにキープアライブするスレッドを起動"""
    def _db_keepalive():
        time.sleep(5)  # worker起動直後は少し待つ
        while True:
            try:
                from app import get_conn
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT 1")
                    cur.close()
            except Exception:
                pass
            time.sleep(180)  # 3分ごと

    threading.Thread(target=_db_keepalive, daemon=True).start()
