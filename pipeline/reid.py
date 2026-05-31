"""
pipeline/reid.py
────────────────
Cross-session Re-ID using YOLO11's built-in embedding features.

Two use cases:
  1. Re-entry: same person exits and returns within 15 minutes
  2. Cross-camera dedup: same person seen by entry + floor camera

Approach:
  YOLO11 with BoT-SORT + with_reid=True produces per-track
  appearance embeddings internally. We extract the bbox crop
  and compute a lightweight color histogram embedding for
  cross-session matching (since YOLO's internal ReID only
  works within-session).
"""
import cv2
import numpy as np
from datetime import datetime, timezone
from dataclasses import dataclass


@dataclass
class ExitRecord:
    visitor_id: str
    embedding:  np.ndarray
    exit_time:  datetime
    camera_id:  str


class ReIDGallery:
    """
    Stores embeddings of recently exited visitors.
    Used to detect re-entry and cross-camera duplicates.
    """
    REENTRY_TTL_SECONDS    = 900   # 15 minutes
    REENTRY_THRESHOLD      = 0.82  # cosine similarity
    CROSS_CAM_TTL_SECONDS  = 30    # 30 seconds
    CROSS_CAM_THRESHOLD    = 0.78

    def __init__(self):
        self._exited:    dict[str, ExitRecord] = {}  # visitor_id → record
        self._active:    dict[str, ExitRecord] = {}  # visitor_id → record (cross-cam)

    def add_exit(self, visitor_id: str, embedding: np.ndarray,
                 camera_id: str, ts: datetime):
        self._exited[visitor_id] = ExitRecord(visitor_id, embedding, ts, camera_id)
        self._prune()

    def add_active(self, visitor_id: str, embedding: np.ndarray,
                   camera_id: str, ts: datetime):
        self._active[visitor_id] = ExitRecord(visitor_id, embedding, ts, camera_id)
        self._prune()

    def find_reentry(self, embedding: np.ndarray,
                     now: datetime) -> str | None:
        """Return visitor_id if this embedding matches a recent exit."""
        best_vid, best_sim = None, 0.0
        for vid, record in self._exited.items():
            age = (now - record.exit_time).total_seconds()
            if age > self.REENTRY_TTL_SECONDS:
                continue
            sim = self._cosine(embedding, record.embedding)
            if sim > best_sim:
                best_sim, best_vid = sim, vid

        if best_sim >= self.REENTRY_THRESHOLD:
            del self._exited[best_vid]
            return best_vid
        return None

    def find_cross_cam_dup(self, embedding: np.ndarray,
                            camera_id: str, now: datetime) -> str | None:
        """Return visitor_id if this is a cross-camera duplicate."""
        for vid, record in self._active.items():
            if record.camera_id == camera_id:
                continue   # same camera = not a cross-cam dup
            age = (now - record.exit_time).total_seconds()
            if age > self.CROSS_CAM_TTL_SECONDS:
                continue
            sim = self._cosine(embedding, record.embedding)
            if sim >= self.CROSS_CAM_THRESHOLD:
                return vid
        return None

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _prune(self):
        now = datetime.now(timezone.utc)
        self._exited = {
            v: r for v, r in self._exited.items()
            if (now - r.exit_time).total_seconds() < self.REENTRY_TTL_SECONDS
        }
        self._active = {
            v: r for v, r in self._active.items()
            if (now - r.exit_time).total_seconds() < self.CROSS_CAM_TTL_SECONDS
        }

    @staticmethod
    def extract_embedding(frame: np.ndarray, bbox: tuple) -> np.ndarray:
        """
        Color histogram embedding from bbox crop.
        Fast, CPU-friendly, sufficient for re-entry matching
        when combined with the time-window constraint.
        32-bin HSV histogram flattened to 96-dim vector.
        """
        x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return np.zeros(96)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None,
                            [16, 4, 4], [0, 180, 0, 256, 0, 256])
        hist = cv2.normalize(hist, hist).flatten()
        return hist.astype(np.float32)
