"""Read-only what-if customer simulation for the hackathon.

This module NEVER writes to database or calls geolocation services. Its traffic
numbers and customers are explicitly fictional. Live appointment offers use the
queue_engine delay_recommendations function, not this synthetic timeline.
"""
from datetime import datetime, timedelta

BASE_DAY = "2026-10-13"  # illustrative clinic day, NOT today's live bookings


def at(minutes: int) -> str:
    return (datetime.fromisoformat(f"{BASE_DAY}T00:00:00") + timedelta(minutes=minutes)).strftime("%H:%M")


def simulate(scenario: str, traffic_delay_minutes: int, max_delay_minutes: int, action: str) -> dict:
    now = 9 * 60 + 35  # scenario clock: 09:35
    original = 10 * 60
    duration, buffer, grace = 30, 5, 10
    # 15 minutes' usual journey; simulated congestion adds 0..75 minutes.
    eta = 15 + traffic_delay_minutes
    arrival = now + eta
    others = ([('Priya', 11 * 60 + 15), ('Arjun', 11 * 60 + 50)]
              if scenario != 'fully_booked' else
              [('Priya', 10 * 60 + 30), ('Arjun', 11 * 60 + 5)])
    timeline = [{"customer": "Rahul", "role": "Late customer", "time": at(original),
                 "original_time": at(original), "status": "confirmed", "kind": "owner"}]
    for customer, start in others:
        timeline.append({"customer": customer, "role": "Existing confirmed customer",
                         "time": at(start), "original_time": at(start), "status": "confirmed", "kind": "existing"})
    timeline.append({"customer": "Meera", "role": "Waitlisted customer (12-min ETA)",
                     "time": None, "original_time": None, "status": "waiting", "kind": "waitlist"})
    events = [f"09:35 · Rahul shares a simulated ETA of {eta} minutes."]
    options = []
    on_time = arrival <= original + grace
    if on_time:
        events.append(f"{at(arrival)} · Expected to arrive within the clinic's {grace}-minute grace period; booking stays at 10:00.")
    else:
        events.append(f"{at(arrival)} · Rahul would exceed the grace period; search for 15/30-minute recovery slots.")
        for delay in (15, 30):
            if delay > max_delay_minutes:
                continue
            proposed = original + delay
            # Must leave >= 5 minutes between ETA and new start; never move confirmed people.
            if arrival + buffer > proposed:
                continue
            if any(proposed < start + duration + buffer and start < proposed + duration + buffer
                   for _, start in others):
                continue
            options.append({"delay_minutes": delay, "time": at(proposed),
                            "reason": "Reachable with five-minute buffer and no confirmed booking conflict"})
    selected = options[0] if options else None
    decision = 'keep_original' if on_time else 'offer_delay' if selected else 'no_safe_slot'
    if selected and action == 'accept':
        timeline[0]['time'] = selected['time']
        timeline[0]['status'] = 'rescheduled'
        timeline[-1]['time'] = at(original)
        timeline[-1]['status'] = 'offer_pending'
        events.append(f"Rahul accepts {selected['time']}; the 10:00 slot is released for eligible waitlist matching.")
        events.append('Meera receives a temporary offer for 10:00, NOT a forced booking; acceptance is required.')
        outcome = 'accepted'
    elif selected and action == 'decline':
        events.append('Rahul declines; the 10:00 booking stays reserved. No other customer is moved.')
        outcome = 'declined'
    elif selected:
        events.append(f"Offer Rahul {selected['time']}; hold the 10:00 booking until he accepts.")
        outcome = 'offer_pending'
    elif on_time:
        outcome = 'on_time'
    else:
        events.append('No safe time within the delay cap. Keep booking reserved pending policy or staff review.')
        outcome = 'manual_review'
    timeline.sort(key=lambda row: row['time'] or '99:99')
    return {
        "simulation_only": True,
        "traffic_provider": "fictional ETA - not Google Maps or actual traffic",
        "scenario": scenario, "clock": at(now), "eta_minutes": eta,
        "predicted_arrival": at(arrival), "original_time": at(original),
        "max_delay_minutes": max_delay_minutes, "decision": decision,
        "outcome": outcome, "options": options, "selected": selected,
        "confirmed_customers_displaced": 0,
        "waitlist_offer_created_in_demo": bool(selected and action == 'accept'),
        "customers": timeline, "events": events,
        "policy": "No automated displacement. Customer consent required. Original remains reserved until acceptance. Waitlist acceptance is separate."
    }
