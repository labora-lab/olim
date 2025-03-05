def shorten(string: str, n: int = 80, add: str = " (...)") -> str:
    """Finds the first space after n characters and truncate the
        string there.

    Args:
        string (str): Original string.
        n (int): Minimum number of characters to prese¨
        str: Shortened string.
    """
    pos = string.find(" ", n)
    if pos != -1:
        return string[:pos] + add
    else:
        return string
