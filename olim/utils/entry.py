from olim import entry_types


def get_all_hidden(project_id: int) -> list:
    hidden = []
    for mod in dir(entry_types):
        module = getattr(entry_types, mod)
        if hasattr(module, "get_all_hidden"):
            hidden += module.get_all_hidden(project_id)
    return hidden


def have_hidden() -> bool:
    have_hidden = False
    for mod in dir(entry_types):
        module = getattr(entry_types, mod)
        if hasattr(module, "have_hidden"):
            have_hidden = have_hidden or module.have_hidden()
    return have_hidden
