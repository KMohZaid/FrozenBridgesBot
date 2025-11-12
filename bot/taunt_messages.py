"""
Taunt and comedy messages for Frozen Bridges game events.
"""

import os
import random

# Check if taunt messages are enabled
TAUNTS_ENABLED = os.getenv("ENABLE_TAUNT_MESSAGES", "true").lower() == "true"

# Taunt messages for rolling a 1 (bad luck)
ROLL_ONE_TAUNTS = [
    "Ouch! That's a critical fail! 😬",
    "A 1? Really? Did you forget how dice work? 🎲",
    "The dice gods are NOT on your side today! 😅",
    "Well... at least you tried! 🤷",
    "That's the worst roll possible. Congratulations? 🏆",
    "Even a broken clock is right twice a day... but not you! ⏰",
    "The dice have spoken: NOPE! 🙅",
]

# Taunt messages for rolling a 6 (great luck)
ROLL_SIX_TAUNTS = [
    "BOOM! Maximum power! 💪",
    "Six! The dice love you! 🎲✨",
    "Perfection! Chef's kiss! 👨‍🍳💋",
    "Someone's got lady luck on their side! 🍀",
    "Is that dice rigged? Too good! 😎",
    "Six! You're on fire! 🔥",
    "The dice gods smile upon you! ⚡",
]

# Taunt messages for a tie
TIE_TAUNTS = [
    "It's a tie! You're equally matched... or equally unlucky! 😂",
    "Same number! Great minds think alike (or fools seldom differ)! 🤔",
    "Tied! Time to settle this like true warriors... with another roll! ⚔️",
    "Wow, you both rolled the same? What are the odds! 🎭",
    "A draw! The tension continues! 😱",
    "Perfectly balanced, as all things should be... now roll again! ⚖️",
]

# Taunt messages when the question is revealed
QUESTION_REVEALED_TAUNTS = [
    "The secret is OUT! Truth revealed! 🔥",
    "Oooh, spicy! Everyone knows now! 🌶️",
    "The truth shall set you free (and embarrass you)! 😳",
    "Exposed! No secrets on this bridge! 🌉",
    "Plot twist: Everyone can see it now! 📖",
    "Secret? What secret? It's public now! 📢",
    "And the truth is... *drumroll* 🥁",
]

# Taunt messages when the question stays secret
QUESTION_HIDDEN_TAUNTS = [
    "Safe! The secret stays locked! 🔐",
    "Phew! Mystery preserved! 🤫",
    "Your secret is safe... for now! 🕵️",
    "Dodged a bullet there! Nobody knows! 💨",
    "The vault remains sealed! 🏦",
    "Nice save! Your lips are sealed! 🤐",
    "What happens on the bridge, stays on the bridge! 🌉",
]


def get_taunt(event_type: str) -> str:
    """
    Get a random taunt message for a specific event.

    Args:
        event_type: One of 'roll_one', 'roll_six', 'tie', 'revealed', 'hidden'

    Returns:
        A random taunt message, or empty string if taunts are disabled
    """
    if not TAUNTS_ENABLED:
        return ""

    taunts_map = {
        "roll_one": ROLL_ONE_TAUNTS,
        "roll_six": ROLL_SIX_TAUNTS,
        "tie": TIE_TAUNTS,
        "revealed": QUESTION_REVEALED_TAUNTS,
        "hidden": QUESTION_HIDDEN_TAUNTS,
    }

    taunt_list = taunts_map.get(event_type, [])
    if not taunt_list:
        return ""

    return random.choice(taunt_list)
