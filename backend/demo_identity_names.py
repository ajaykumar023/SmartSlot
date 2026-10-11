"""Stable, entirely fictional display names for the AETHERX showcase dataset.

The input keys are the original deterministic seed labels, not employee IDs.
This allows the naming repair to preserve existing appointments, staff FK IDs,
absence intervals, email-based demo identities, and recovery scenarios.
"""
from __future__ import annotations

from itertools import chain

ROSTER_SPEC = {
    "showcase_salon_a": {
        "base": ("Demo Stylist A", "Demo Stylist B"),
        "new": ("Stylist", 7),
        "helpers": (("Receptionist", 2), ("Salon assistant", 2), ("Salon manager", 1)),
        "names": (
            "Aarav Mehta", "Meera Kapoor", "Kabir Shah", "Priya Nair", "Aditya Rao",
            "Nisha Reddy", "Vihaan Sethi", "Sara Fernandes", "Rohan Malhotra",
            "Kavya Menon", "Arjun Banerjee", "Tara Iyer", "Sameer Joshi", "Ananya Desai",
        ),
    },
    "showcase_salon_b": {
        "base": ("Demo Backup Stylist",),
        "new": ("Stylist", 7),
        "helpers": (("Receptionist", 2), ("Salon assistant", 1), ("Salon manager", 1)),
        "names": (
            "Reyansh Verma", "Ishita Sharma", "Dev Patel", "Zoya Merchant",
            "Neil Bhat", "Diya Singh", "Armaan Walia", "Pooja Shetty",
            "Karan Bedi", "Rhea Bose", "Vikram Suri", "Sana Qureshi",
        ),
    },
    "showcase_clinic": {
        "base": ("Demo Clinician",),
        "new": ("Clinician", 6),
        "helpers": (("Nurse", 3), ("Receptionist", 2), ("Clinic coordinator", 1), ("Clinic manager", 1)),
        "names": (
            "Anika Sood", "Farhan Ali", "Ritika Chawla", "Harish Kulkarni",
            "Leena Mathew", "Yusuf Khan", "Neha Saxena", "Varun Pillai",
            "Aditi Prasad", "Mihir Dutta", "Sanya Ghosh", "Kunal Thakur",
            "Radhika Anand", "Omkar Naik",
        ),
    },
    "showcase_repair": {
        "base": ("Demo Technician",),
        "new": ("Technician", 7),
        "helpers": (("Front desk", 2), ("Service supervisor", 1), ("Inventory assistant", 1)),
        "names": (
            "Nikhil Arora", "Ayesha Siddiqui", "Pranav Bansal", "Jiya Deshpande",
            "Shreyas Iyer", "Maya Thomas", "Abhinav Jain", "Keerthi Krishnan",
            "Yash Chopra", "Simran Oberoi", "Ravi Narayanan", "Tanvi Bhalla",
        ),
    },
    "showcase_consult": {
        "base": ("Demo Consultant",),
        "new": ("Consultant", 4),
        "helpers": (("Scheduling coordinator", 2), ("Office manager", 1)),
        "names": (
            "Aman Agarwal", "Isha Batra", "Siddharth Sen", "Palak Trivedi",
            "Rahil Merchant", "Nandini George", "Shivam Grover", "Elina D'Souza",
        ),
    },
}


def _legacy_names(business_key: str, spec: dict) -> tuple[str, ...]:
    title = business_key.replace("showcase_", "").replace("_", " ").title()
    labels = list(spec["base"])
    profession, count = spec["new"]
    labels.extend(f"Demo {title} {profession} {i:02d}" for i in range(1, count + 1))
    for helper_title, quantity in spec["helpers"]:
        labels.extend(f"Demo {title} {helper_title} {i:02d}" for i in range(1, quantity + 1))
    return tuple(labels)


STAFF_DISPLAY_NAMES = {
    business: dict(zip(_legacy_names(business, spec), spec["names"]))
    for business, spec in ROSTER_SPEC.items()
}
assert all(len(_legacy_names(key, spec)) == len(spec["names"]) for key, spec in ROSTER_SPEC.items())
_all_staff_names = list(chain.from_iterable(spec["names"] for spec in ROSTER_SPEC.values()))
assert len(_all_staff_names) == len(set(_all_staff_names)) == 60


def employee_name(business_key: str, original_name: str) -> str:
    """Identity-safe seed name conversion; unknown names are left untouched."""
    return STAFF_DISPLAY_NAMES.get(business_key, {}).get(original_name, original_name)


CUSTOMER_FIRST_NAMES = (
    "Aanya", "Bhavya", "Chirag", "Dhruv", "Esha", "Faisal", "Gauri", "Harsh",
    "Inaya", "Jatin", "Kiara", "Laksh", "Manya", "Naman", "Ojas", "Pihu",
    "Qasim", "Roshni", "Sahil", "Trisha", "Uma", "Vedant", "Yamini", "Zubin", "Ritu",
)
CUSTOMER_LAST_NAMES = (
    "Chandra", "Nayak", "Kapur", "Kashyap", "Srinivasan", "Fernandes", "Sheikh",
    "Bhattacharya", "Mishra", "Dhar", "Kohli", "Jadhav", "Narang",
)


def fictional_customer_name(number: int) -> str:
    """Return one stable, unique full name for demo customer 1..100."""
    if not 1 <= number <= 100:
        raise ValueError("demo customer number must be 1..100")
    ix = number - 1
    first = CUSTOMER_FIRST_NAMES[ix % len(CUSTOMER_FIRST_NAMES)]
    last = CUSTOMER_LAST_NAMES[((ix % len(CUSTOMER_FIRST_NAMES)) * 7 + ix // len(CUSTOMER_FIRST_NAMES)) % len(CUSTOMER_LAST_NAMES)]
    return f"{first} {last}"


assert len({fictional_customer_name(n) for n in range(1, 101)}) == 100

SCENARIO_CUSTOMERS = {
    "demo.local@aetherx.example": "Asha Malhotra",
    "demo.route@aetherx.example": "Rohan Venkatesh",
    "demo.clinic@aetherx.example": "Mira Saldanha",
    "demo.repair@aetherx.example": "Akash Shetty",
    "demo.consult@aetherx.example": "Naina Sabharwal",
    "demo.cancel@aetherx.example": "Varun Khanna",
}
WAITLIST_CUSTOMERS = {
    "demo.reema@aetherx.example": "Reema Chandra",
    "demo.nikhil@aetherx.example": "Nikhil Parekh",
    "demo.tara@aetherx.example": "Tara Mukherjee",
}
