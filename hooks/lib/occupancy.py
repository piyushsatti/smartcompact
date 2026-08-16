"""Occupancy, and which of three named zones it falls in against a trigger.

Deliberately narrow: this module answers "how full is the window, and how
worried should we be," relative to this client's own measured compaction
point. It does not know the model's real ceiling; that is a later step's
question, and nothing here reads or infers a model context window.
"""

# Headroom Claude Code keeps back from autoCompactWindow before it actually
# compacts, measured, not documented. Two clusters of automatic compaction
# boundaries in the corpus, one under a 250,000 window and one under 500,000,
# put the earliest fire 33,425 and 34,066 below their window. Two independent
# estimates 641 tokens apart, so this is a constant and not a fraction of the
# window.
RESERVE = 33_400


def occupancy(usage):
    """One message's window pressure. Never a running total, never summed.

    Must stay byte-identical to research/harness/distill.py's function of
    the same name: a later verification step compares the two, and a second
    implementation that drifted would make that comparison meaningless. The
    isinstance guard is the one addition over the research version, because
    a hook's input has not already been validated by a human running a
    one-off script.
    """
    if not isinstance(usage, dict):
        return 0
    return (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )


def trigger_point(window):
    """The occupancy at which this client compacts, or None if window can't anchor one.

    None rather than a guess: a caller with no usable window has nothing
    honest to compare occupancy against, and RESERVE subtracted from a bad
    number is still a bad number.
    """
    if not isinstance(window, (int, float)) or window <= 0:
        return None
    return window - RESERVE


def zone(value, trigger, soft, hard):
    """One of "green", "orange", "red": value's position relative to trigger.

    None only when trigger is None, so a session whose trigger is unknown is
    reported as unanchored rather than shown a colour nothing justifies. Any
    other malformed argument returns None too, caught below rather than
    raising. Both edges are computed before either comparison runs, on
    purpose: value < edge_soft alone can already decide "green" without ever
    touching hard, and a malformed hard must not go uncaught just because
    the answer happened not to need it.
    """
    if trigger is None:
        return None
    try:
        edge_soft = soft * trigger
        edge_hard = hard * trigger
        if value < edge_soft:
            return "green"
        if value < edge_hard:
            return "orange"
        return "red"
    except TypeError:
        return None
