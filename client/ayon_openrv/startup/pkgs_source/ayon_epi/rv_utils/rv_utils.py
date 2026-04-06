try:
    from rapidfuzz import process, fuzz

    def fuzzy_match(word: str, candidates: list[str], limit: int = 20) -> list[str]:
        results = process.extract(
            word,
            candidates,
            scorer=fuzz.QRatio,
            score_cutoff=30,
            limit=limit,
        )
        return [match for match, score, _ in results]

except ImportError:
    pass
    import sys
    import logging

    exe_path = sys.executable.removesuffix("rv.exe")
    log_path = f'"{exe_path}py-interp.exe" -m pip install rapidfuzz'

    logging.warning(
        f"[rvpython] rapidfuzz not available — autocomplete will be limited.\n"
        f"To install: {log_path}"
    )

    def fuzzy_match(word: str, candidates: list[str], limit: int = 20) -> list[str]:
        """Fallback to startswith matching."""
        return [c for c in candidates if c.lower().startswith(word.lower())][:limit]
