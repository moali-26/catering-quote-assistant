"""Part A: owner menu editing (name, description, price, availability).

    from menu_admin import MenuService, SQLiteMenuStore
    service = MenuService(SQLiteMenuStore('menus.sqlite3'), clock=server_now)

See docs/menu-editing.md.
"""
from .editing import MenuEditError, apply_menu_changes, owner_menu_view, validate_menu_structure
from .service import MenuService
from .storage import MenuConflict, MenuNotFound, SQLiteMenuStore

__all__ = ['MenuService', 'SQLiteMenuStore', 'MenuEditError', 'MenuConflict', 'MenuNotFound',
           'apply_menu_changes', 'owner_menu_view', 'validate_menu_structure']
