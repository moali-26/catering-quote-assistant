"""Owner menu management: load, view, edit with revision checks.

The application verifies Supabase Auth first and passes the verified account ID as
actor_id. owner_id identifies the business (the owner's account ID, the same value
quotes use). Never take actor_id/owner_id from browser fields.
"""
import copy

from .editing import apply_menu_changes, owner_menu_view, validate_menu_structure
from .storage import MenuConflict, MenuNotFound

CHANGE_LOG_LIMIT = 200


def _stamp(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('clock must return a timezone-aware datetime')
    return now.isoformat()


class MenuService:
    def __init__(self, store, *, clock):
        self.store = store
        self.clock = clock

    def seed(self, owner_id, menu):
        """Server-only setup: store the starting menu (e.g. data/demo/menu.json). Not an HTTP action."""
        validate_menu_structure(menu)
        record = {'owner_id': owner_id, 'revision': 1, 'menu': copy.deepcopy(menu),
                  'updated_at': _stamp(self.clock()), 'updated_by': None, 'change_log': []}
        self.store.create(record)
        return owner_menu_view(record)

    def current_menu(self, owner_id):
        """Trusted server read for pricing/AI context. Customers never edit through this."""
        return self.store.get(owner_id)['menu']

    def owner_view(self, owner_id, *, actor_id):
        self._require_owner(owner_id, actor_id)
        return owner_menu_view(self.store.get(owner_id))

    def update(self, owner_id, changes, *, actor_id, expected_revision):
        """Apply owner edits atomically. Returns the refreshed owner view plus what changed.

        expected_revision is the revision shown on the owner's page; a stale value
        raises MenuConflict so a second tab cannot silently overwrite edits.
        """
        self._require_owner(owner_id, actor_id)
        record = self.store.get(owner_id)
        if record['revision'] != expected_revision:
            raise MenuConflict('menu changed since you loaded it: reload and try again')
        menu, applied = apply_menu_changes(record['menu'], changes)
        now = _stamp(self.clock())
        log = record.get('change_log', []) + [dict(entry, at=now, by=actor_id) for entry in applied]
        updated = {'owner_id': owner_id, 'revision': expected_revision + 1, 'menu': menu,
                   'updated_at': now, 'updated_by': actor_id,
                   'change_log': log[-CHANGE_LOG_LIMIT:]}
        self.store.save(updated, expected_revision=expected_revision)
        return dict(owner_menu_view(updated), applied=applied)

    def change_log(self, owner_id, *, actor_id):
        self._require_owner(owner_id, actor_id)
        return list(reversed(self.store.get(owner_id).get('change_log', [])))

    @staticmethod
    def _require_owner(owner_id, actor_id):
        if not isinstance(actor_id, str) or not actor_id or actor_id != owner_id:
            # Same error as a missing menu: do not reveal other businesses' menus exist.
            raise MenuNotFound('menu not found')
