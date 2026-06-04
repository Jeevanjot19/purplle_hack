"""
Pipeline Data Feed Simulator

Generates realistic CCTV event streams simulating visitor journeys:
  ENTRY → ZONE_DWELL(s) → BILLING_QUEUE → EXIT

Also generates POS transactions and queue state updates.
Can be run continuously or one-shot for load testing.

Usage:
  python pipeline/simulator.py --speed 1.0 --duration 3600  # Run 1 hour of data at 1x speed
  python pipeline/simulator.py --speed 5.0                  # 5x speedup for demos
"""

import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone
import httpx
import argparse
import structlog
import os

logger = structlog.get_logger()

# Config
API_URL = os.getenv("API_URL", "http://localhost:8000")
STORES = ["ST1008"]
ZONES = ["APPAREL", "ELECTRONICS", "GROCERY", "CHECKOUT"]
CAMERAS = {
    "ENTRY": "CAM_ENTRY_01",
    "ZONE_APPAREL": "CAM_ZONE_A",
    "ZONE_ELECTRONICS": "CAM_ZONE_E",
    "ZONE_GROCERY": "CAM_ZONE_G",
    "BILLING": "CAM_BILLING_01",
}

class VisitorJourney:
    """Simulates a single visitor's journey through the store"""
    def __init__(self, store_id: str, start_time: datetime, speed_factor: float = 1.0):
        self.store_id = store_id
        self.visitor_id = f"VIS_{uuid.uuid4().hex[:8]}"
        self.entry_time = start_time
        self.start_time = start_time
        self.speed_factor = speed_factor
        self.session_seq = 1
        self.zones_visited = []
        self.current_zone = None
        self.will_convert = random.random() < 0.15  # 15% conversion rate
        self.queue_wait_time = random.randint(30, 300) if self.will_convert else 0
        
    def event_time(self, seconds_from_start: float) -> datetime:
        """Convert relative seconds to actual timestamp with speed factor applied"""
        return self.entry_time + timedelta(seconds=seconds_from_start / self.speed_factor)
    
    async def generate_journey(self) -> list[dict]:
        """Generate all events for this visitor's journey"""
        events = []
        elapsed = 0
        
        # ENTRY event
        events.append({
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,
            "camera_id": CAMERAS["ENTRY"],
            "visitor_id": self.visitor_id,
            "event_type": "ENTRY",
            "timestamp": self.event_time(elapsed).isoformat(),
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": random.uniform(0.85, 0.99),
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": self.session_seq},
        })
        elapsed += random.uniform(2, 8)
        
        # ZONE_ENTER and ZONE_DWELL events (if converting)
        if self.will_convert:
            num_zones = random.randint(1, 3)
            for _ in range(num_zones):
                zone = random.choice(ZONES)
                self.zones_visited.append(zone)
                dwell_ms = random.randint(30000, 300000)  # 30sec - 5min per zone
                
                events.append({
                    "event_id": str(uuid.uuid4()),
                    "store_id": self.store_id,
                    "camera_id": CAMERAS.get(f"ZONE_{zone}", "CAM_ZONE_X"),
                    "visitor_id": self.visitor_id,
                    "event_type": "ZONE_DWELL",
                    "timestamp": self.event_time(elapsed).isoformat(),
                    "zone_id": zone,
                    "dwell_ms": dwell_ms,
                    "is_staff": False,
                    "confidence": random.uniform(0.85, 0.99),
                    "metadata": {
                        "queue_depth": None,
                        "sku_zone": zone,
                        "session_seq": self.session_seq,
                    },
                })
                elapsed += dwell_ms / 1000 + random.uniform(2, 10)
            
            # BILLING_QUEUE_JOIN event
            events.append({
                "event_id": str(uuid.uuid4()),
                "store_id": self.store_id,
                "camera_id": CAMERAS["BILLING"],
                "visitor_id": self.visitor_id,
                "event_type": "BILLING_QUEUE_JOIN",
                "timestamp": self.event_time(elapsed).isoformat(),
                "zone_id": "CHECKOUT",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": random.uniform(0.85, 0.99),
                "metadata": {
                    "queue_depth": random.randint(1, 5),
                    "sku_zone": "CHECKOUT",
                    "session_seq": self.session_seq,
                },
            })
            elapsed += self.queue_wait_time
        
        # EXIT event (always happens)
        events.append({
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,
            "camera_id": CAMERAS["ENTRY"],
            "visitor_id": self.visitor_id,
            "event_type": "EXIT",
            "timestamp": self.event_time(elapsed).isoformat(),
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": random.uniform(0.85, 0.99),
            "metadata": {
                "queue_depth": None,
                "sku_zone": None,
                "session_seq": self.session_seq,
            },
        })
        
        return events


async def post_events(events: list[dict], client: httpx.AsyncClient) -> bool:
    """POST events to ingestion endpoint"""
    try:
        payload = {"events": events}
        response = await client.post(
            f"{API_URL}/events/ingest",
            json=payload,
            timeout=5.0,
        )
        if response.status_code == 200:
            result = response.json()
            if result.get("accepted", 0) > 0:
                logger.info("events_posted", count=result["accepted"])
                return True
        logger.warn("post_failed", status=response.status_code)
        return False
    except Exception as e:
        logger.error("post_error", error=str(e))
        return False


async def simulate_store(
    store_id: str,
    duration_seconds: float,
    speed_factor: float,
    client: httpx.AsyncClient,
) -> None:
    """Simulate visitor traffic for a single store"""
    logger.info("simulation_start", store=store_id, duration=duration_seconds, speed=speed_factor)
    
    start_time = datetime.now(timezone.utc)
    sim_time = start_time
    end_time = start_time + timedelta(seconds=duration_seconds)
    
    # Generate arrival times (Poisson distribution - avg 3 visitors/min)
    arrival_interval = 20  # seconds between arrivals (in real time)
    next_arrival = sim_time
    
    visitors_generated = 0
    events_posted = 0
    
    while sim_time < end_time:
        # Generate a visitor journey at next arrival time
        if sim_time >= next_arrival:
            journey = VisitorJourney(store_id, sim_time, speed_factor)
            events = await journey.generate_journey()
            
            if await post_events(events, client):
                events_posted += len(events)
                visitors_generated += 1
            
            next_arrival += timedelta(seconds=arrival_interval)
        
        # Advance simulation time
        sim_time += timedelta(seconds=arrival_interval / speed_factor)
        await asyncio.sleep(0.1)  # Avoid busy-waiting
    
    logger.info(
        "simulation_complete",
        store=store_id,
        visitors=visitors_generated,
        events=events_posted,
    )


async def main():
    parser = argparse.ArgumentParser(description="CCTV Event Pipeline Simulator")
    parser.add_argument(
        "--stores",
        default="ST1008",
        help="Comma-separated store IDs to simulate",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=300,
        help="Simulation duration in seconds (default: 300 = 5 minutes)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speedup factor (5.0 = 5x faster, default: 1.0)",
    )
    
    args = parser.parse_args()
    stores = [s.strip() for s in args.stores.split(",")]
    
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )
    
    async with httpx.AsyncClient() as client:
        tasks = [
            simulate_store(store, args.duration, args.speed, client)
            for store in stores
        ]
        await asyncio.gather(*tasks)
    
    logger.info("all_simulations_complete")


if __name__ == "__main__":
    asyncio.run(main())
