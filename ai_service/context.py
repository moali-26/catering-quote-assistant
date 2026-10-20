"""Trusted server-side context. Nothing here comes from the model.

The model never supplies prices, tax jurisdiction, delivery distance, the
current time, or which business it is quoting for.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo('America/Los_Angeles')

# DEMO ONLY. No geocoding exists yet. Distances are rough driving miles from the
# caterer's Torrance location and are classroom assumptions, not measurements.
# Replace with a real resolver (or an owner-verified field) before production.
DEMO_CITY_TABLE = {
    'culver city': ('Culver City', 15.0),
    'torrance': ('Torrance', 3.0),
}


def demo_location_resolver(address: str) -> Optional[Tuple[str, float]]:
    """Map an address to (tax_location, delivery_miles) using the demo table.

    Returns None when the city is not recognised, so the conversation tells the
    customer the address needs verification instead of guessing.
    """
    text = (address or '').lower()
    for key, value in DEMO_CITY_TABLE.items():
        if key in text:
            return value
    return None


@dataclass
class ServerContext:
    menu: Dict[str, Any]
    rules: Dict[str, Any]
    capacity: Optional[Dict[str, Any]] = None
    # Injected clock so tests and the eval can freeze "today".
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(PACIFIC))
    # address -> (tax_location, delivery_miles) or None if unknown.
    resolve_location: Callable[[str], Optional[Tuple[str, float]]] = demo_location_resolver

    def now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError('ServerContext clock must return a timezone-aware datetime')
        return value

    @property
    def business_name(self) -> str:
        return self.menu.get('meta', {}).get('branding', {}).get('display_name', 'the caterer')

    def pickup_tax_location(self) -> Optional[str]:
        """Pickup is taxed at the business location."""
        city = self.rules.get('delivery', {}).get('origin', {}).get('city')
        return city if city in self.rules.get('tax', {}).get('rates', {}) else None

    def location_for(self, arguments: Dict[str, Any]) -> Tuple[Optional[str], Optional[float]]:
        """Resolve tax_location and delivery_miles for the current tool arguments."""
        mode = arguments.get('service_mode') if isinstance(arguments, dict) else None
        if mode == 'pickup':
            return self.pickup_tax_location(), None
        if mode == 'delivery':
            address = arguments.get('address')
            if isinstance(address, str) and address.strip():
                resolved = self.resolve_location(address)
                if resolved:
                    return resolved
        return None, None
