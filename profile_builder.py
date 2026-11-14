"""
profile_builder.py — שיחה אינטראקטיבית עם AGY לבניית פרופיל חיפוש
"""
import asyncio
import yaml
import json
from pathlib import Path
from google.antigravity import Agent, LocalAgentConfig
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()
CONFIG_PATH = Path(__file__).parent / "config.yaml"

SYSTEM_INSTRUCTIONS = """
אתה עוזר ידידותי שעוזר לזוג למצוא דירה להשכרה בישראל.
שאל שאלות בעברית בצורה חמה ומכבדת.
אחרי שאספת את כל המידע, החזר JSON תקני בלבד (ללא הסברים נוספים) עם המבנה הבא:

{
  "locations": ["שם עיר/שכונה"],
  "price_min": מספר,
  "price_max": מספר,
  "rooms_min": מספר,
  "rooms_max": מספר,
  "floor_min": מספר,
  "require_elevator": true/false,
  "require_parking": true/false,
  "require_balcony": true/false,
  "require_mamad": true/false,
  "require_pets": true/false,
  "blacklist_keywords": ["מילה"],
  "bonus_keywords": ["מילה"]
}

שאל על:
1. ערים/שכונות מועדפות
2. טווח מחירים (תשאל בנפרד על מינימום ומקסימום)
3. מספר חדרים
4. קומה מינימום (אם יש העדפה)
5. דרישות חובה: מעלית, חניה, מרפסת, ממ"ד, חיות מחמד
6. האם יש דברים שבהחלט לא רוצים (מילות blacklist)
7. מה חשוב במיוחד (מילות bonus)

אחרי שסיימת לשאול הכל, אמור "תודה! מעדכן את ההגדרות..." ואז החזר את ה-JSON.
"""


async def run_profile_setup():
    """הרצת שיחה אינטראקטיבית לבניית פרופיל"""
    console.print(Panel(
        "[bold cyan]🏠 ברוכים הבאים ל-DiraBot![/bold cyan]\n"
        "בוא נגדיר יחד את הדירה המושלמת שלכם.\n"
        "ענה על השאלות שלי ואסדר הכל אוטומטית 🎉",
        border_style="cyan"
    ))

    config = LocalAgentConfig(
        system_instructions=SYSTEM_INSTRUCTIONS,
    )

    collected_json = None

    async with Agent(config) as agent:
        # פתיחת השיחה
        opening = await agent.chat(
            "שלום! אני כאן לעזור לכם למצוא את הדירה המושלמת. בואו נתחיל!"
        )
        agent_text = await opening.text()
        console.print(f"\n[bold green]🤖 הסוכן:[/bold green] {agent_text}\n")

        # לולאת שיחה
        while True:
            user_input = Prompt.ask("[bold yellow]אתה[/bold yellow]")
            if user_input.lower() in ["יציאה", "exit", "quit"]:
                break

            response = await agent.chat(user_input)
            response_text = await response.text()
            console.print(f"\n[bold green]🤖 הסוכן:[/bold green] {response_text}\n")

            # בדיקה אם הסוכן החזיר JSON
            if "{" in response_text and "locations" in response_text:
                try:
                    json_start = response_text.index("{")
                    json_end = response_text.rindex("}") + 1
                    json_str = response_text[json_start:json_end]
                    collected_json = json.loads(json_str)
                    console.print("[bold cyan]✅ פרופיל נאסף בהצלחה![/bold cyan]")
                    break
                except (json.JSONDecodeError, ValueError):
                    pass

    if collected_json:
        _update_config(collected_json)
        console.print(Panel(
            "[bold green]✅ ההגדרות עודכנו ב-config.yaml![/bold green]\n"
            f"ניתן לערוך ידנית בכל עת: [cyan]{CONFIG_PATH}[/cyan]",
            border_style="green"
        ))
    else:
        console.print("[yellow]⚠️ לא עודכנו הגדרות. ניתן לערוך ידנית את config.yaml[/yellow]")


def _update_config(profile: dict):
    """עדכון config.yaml עם הפרופיל שנאסף"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # עדכון ערכים
    config["search"]["locations"] = profile.get("locations", config["search"]["locations"])
    config["search"]["price"]["min"] = profile.get("price_min", config["search"]["price"]["min"])
    config["search"]["price"]["max"] = profile.get("price_max", config["search"]["price"]["max"])
    config["search"]["rooms"]["min"] = profile.get("rooms_min", config["search"]["rooms"]["min"])
    config["search"]["rooms"]["max"] = profile.get("rooms_max", config["search"]["rooms"]["max"])
    config["search"]["floor_min"] = profile.get("floor_min", config["search"]["floor_min"])
    config["search"]["require_elevator"] = profile.get("require_elevator", False)
    config["search"]["require_parking"] = profile.get("require_parking", False)
    config["search"]["require_balcony"] = profile.get("require_balcony", False)
    config["search"]["require_mamad"] = profile.get("require_mamad", False)
    config["search"]["require_pets"] = profile.get("require_pets", False)

    if profile.get("blacklist_keywords"):
        config["search"]["blacklist_keywords"] = profile["blacklist_keywords"]
    if profile.get("bonus_keywords"):
        config["search"]["bonus_keywords"] = profile["bonus_keywords"]

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    asyncio.run(run_profile_setup())
