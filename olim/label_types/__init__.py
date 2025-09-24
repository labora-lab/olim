from . import check, open_text, sim_nao, sim_nao_ns, yes_no, yes_no_idk, yes_no_unknown

__all__ = ["check", "open_text", "sim_nao", "sim_nao_ns", "yes_no", "yes_no_idk", "yes_no_unknown"]


def get_label_type_module(label_type):
    """Get the module for a specific label type"""
    if label_type == "sim_nao":
        return sim_nao
    elif label_type == "sim_nao_ns":
        return sim_nao_ns
    elif label_type == "yes_no":
        return yes_no
    elif label_type == "check":
        return check
    elif label_type == "yes_no_unknown":
        return yes_no_unknown
    elif label_type == "yes_no_idk":
        return yes_no_idk
    elif label_type == "open_text":
        return open_text
    else:
        # Default fallback
        return sim_nao


def get_available_label_types():
    """Get all available label types"""
    return [
        ("sim_nao", "Sim/Não"),
        ("sim_nao_ns", "Sim/Não/Não Sei"),
        ("yes_no", "Yes/No"),
        ("check", "Check"),
        ("yes_no_unknown", "Yes/No/Unknown"),
        ("yes_no_idk", "Yes/No/Don't Know"),
        ("open_text", "Open Text"),
    ]


def is_open_text_label(label_type):
    """Check if a label type is open text"""
    if label_type == "open_text":
        module = get_label_type_module(label_type)
        return hasattr(module, 'is_open_text') and module.is_open_text()
    return False 