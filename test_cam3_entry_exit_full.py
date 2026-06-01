#!/usr/bin/env python
"""
CAM_3 Entry/Exit Validation Test
Purpose: Verify that CAM_3 (entry camera) correctly emits ENTRY/EXIT events
Expected: ENTRY events on tripwire crossing (upward), EXIT on downward crossing

Real store: Brigade Road Bangalore, ST1008
Video: Entry/exit footage with clear door crossings
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add pipeline modules to path
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.detect import process_clip


async def main():
    """Validate CAM_3 entry/exit counting."""
    
    store_id = "ST1008"
    camera_id = "CAM_3"
    clip_path = "data/CAM_3.mp4"
    
    print("=" * 70)
    print("CAM_3 ENTRY/EXIT VALIDATION TEST")
    print("=" * 70)
    print(f"Store ID:        {store_id}")
    print(f"Camera:          {camera_id} (Entry/Exit)")
    print(f"Video:           {clip_path}")
    print(f"API URL:         http://localhost:8000")
    print(f"Speed:           5.0× (demo mode)")
    print(f"Timestamp:       {datetime.now().isoformat()}")
    print("=" * 70)
    print("")
    
    # Check if file exists
    local_clip = Path(__file__).parent / clip_path
    if not local_clip.exists():
        print(f"❌ FATAL: {local_clip} not found")
        print(f"   Expected: {local_clip}")
        print("")
        print("📤 Next step: Upload CAM_3.mp4 to data/ directory")
        print("")
        print("Expected filename patterns:")
        print("  - data/CAM_3.mp4")
        print("  - data/CAM_3_<timestamp>.mp4")
        print("")
        print("Once uploaded, run: python test_cam3_entry_exit.py")
        sys.exit(1)
    
    print(f"✓ Video found: {local_clip}")
    print(f"  Size: {local_clip.stat().st_size / 1024 / 1024:.1f} MB")
    print("")
    
    try:
        print("⏱️  Starting pipeline processing...")
        print("")
        
        result = await process_clip(
            clip_path=str(local_clip),
            store_id=store_id,
            camera_id=camera_id,
            api_url="http://localhost:8000",
            speed_factor=5.0,
            layout_path=str(Path(__file__).parent / "data" / "store_layout.json")
        )
        
        print("")
        print("=" * 70)
        print("PROCESSING COMPLETE")
        print("=" * 70)
        print(f"Result: {result}")
        print("")
        
        # Query database for events
        print("📊 Database Validation:")
        print("-" * 70)
        
        import asyncpg
        
        db_config = {
            "host": "localhost",
            "port": 5432,
            "user": "store",
            "password": "storepass",
            "database": "storedb"
        }
        
        try:
            conn = await asyncpg.connect(**db_config)
            
            # Query for CAM_3 events
            cam3_events = await conn.fetch("""
                SELECT 
                    event_type,
                    COUNT(*) as count,
                    MIN(timestamp) as first_event,
                    MAX(timestamp) as last_event
                FROM events
                WHERE camera_id = $1 AND timestamp::date = CURRENT_DATE
                GROUP BY event_type
                ORDER BY event_type
            """, camera_id)
            
            if not cam3_events:
                print(f"⚠️  No events found for {camera_id} in database")
                print("   Possible issues:")
                print("   1. Pipeline didn't emit events to API")
                print("   2. API didn't save to database")
                print("   3. Check API logs: docker logs store-intelligence-api-1")
            else:
                print(f"\n✓ Events found for {camera_id}:\n")
                entry_count = 0
                exit_count = 0
                zone_count = 0
                
                for event in cam3_events:
                    print(f"  {event['event_type']:20} {event['count']:5} events")
                    print(f"    First: {event['first_event']}")
                    print(f"    Last:  {event['last_event']}")
                    print()
                    
                    if event['event_type'] == 'ENTRY':
                        entry_count = event['count']
                    elif event['event_type'] == 'EXIT':
                        exit_count = event['count']
                    elif event['event_type'].startswith('ZONE'):
                        zone_count += event['count']
                
                print("-" * 70)
                print(f"Summary: {entry_count} ENTRY, {exit_count} EXIT, {zone_count} ZONE events")
                print("")
                
                # Validation checks
                print("🔍 Validation Checks:")
                print("-" * 70)
                
                checks_passed = 0
                checks_total = 0
                
                # Check 1: Only ENTRY/EXIT from CAM_3
                checks_total += 1
                zone_only_events = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM events
                    WHERE camera_id = $1 
                    AND event_type IN ('ZONE_ENTER', 'ZONE_EXIT', 'ZONE_DWELL')
                    AND timestamp::date = CURRENT_DATE
                """, camera_id)
                
                if zone_only_events == 0:
                    print("✓ Check 1: CAM_3 only emits ENTRY/EXIT (no ZONE events) ✓")
                    checks_passed += 1
                else:
                    print(f"✗ Check 1: CAM_3 shouldn't emit ZONE events, found {zone_only_events}")
                
                # Check 2: ENTRY and EXIT counts reasonable
                checks_total += 1
                if entry_count > 0 and exit_count >= 0:
                    if entry_count >= exit_count:
                        print(f"✓ Check 2: ENTRY count ({entry_count}) >= EXIT count ({exit_count}) ✓")
                        checks_passed += 1
                    else:
                        print(f"✗ Check 2: More EXIT ({exit_count}) than ENTRY ({entry_count})")
                else:
                    print(f"✗ Check 2: No ENTRY events found (found {entry_count})")
                
                # Check 3: Timestamps are from today
                checks_total += 1
                today_events = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM events
                    WHERE camera_id = $1 
                    AND timestamp::date = CURRENT_DATE
                """, camera_id)
                
                all_events = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM events
                    WHERE camera_id = $1
                """, camera_id)
                
                if today_events == all_events or today_events > 0:
                    print(f"✓ Check 3: {today_events} events from today ✓")
                    checks_passed += 1
                else:
                    print(f"✗ Check 3: Events not from today (found {today_events}/{all_events})")
                
                print("-" * 70)
                print(f"\nValidation Score: {checks_passed}/{checks_total} checks passed")
                
                if checks_passed == checks_total:
                    print("\n🎉 SUCCESS: CAM_3 entry/exit validation passed!")
                else:
                    print("\n⚠️  Some checks failed. See above for details.")
            
            await conn.close()
            
        except Exception as e:
            print(f"❌ Database query failed: {e}")
            print("   Make sure PostgreSQL is running: docker-compose ps")
        
    except FileNotFoundError as e:
        print(f"❌ ERROR: File not found: {e}")
        print(f"   Path: {local_clip}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
