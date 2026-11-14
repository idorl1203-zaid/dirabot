"""
fb_login.py — התחברות חד-פעמית לפייסבוק (חשבון משני)

הרצה:  python fb_login.py
נפתח חלון דפדפן אמיתי. התחבר עם החשבון המשני (כולל 2FA אם צריך),
ואז חזור לטרמינל ולחץ Enter. ה-session יישמר לשימוש חוזר של הסוכן.

⚠️ השתמש רק בחשבון משני/נפרד — לא בחשבון האישי שלך.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scraper.fb_browser import open_fb_context, is_logged_in


async def main():
    print("→ פותח חלון פייסבוק... (אם לא נפתח, המתן כמה שניות)")
    pw, ctx = await open_fb_context(headless=False)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")

    if await is_logged_in(ctx):
        print("✅ כבר מחובר! ה-session תקין.")
    else:
        print("\n" + "=" * 55)
        print("  התחבר עכשיו בחלון שנפתח (עם החשבון המשני).")
        print("  אין צורך ללחוץ כלום כאן — אזהה לבד כשתתחבר.")
        print("  ממתין עד 8 דקות...")
        print("=" * 55)
        # פולינג — מזהה אוטומטית מתי התחברת (בלי stdin אינטראקטיבי)
        for i in range(96):  # 96 * 5ש = 8 דקות
            await asyncio.sleep(5)
            try:
                if await is_logged_in(ctx):
                    break
            except Exception:
                print("⚠️  החלון נסגר לפני סיום ההתחברות.")
                break
            if i % 3 == 2:
                print(f"   ...עדיין ממתין ({(i+1)*5} שניות)")

    if await is_logged_in(ctx):
        cookies = await ctx.cookies("https://www.facebook.com")
        uid = next((c["value"] for c in cookies if c["name"] == "c_user"), "?")
        print(f"✅ ה-session נשמר! (user id: {uid})")
        print("   מעכשיו הסוכן יכול לגלול בקבוצות בלי להתחבר שוב.")
    else:
        print("⚠️  עדיין לא מחובר — הרץ שוב ונסה להתחבר עד הסוף.")

    await ctx.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
