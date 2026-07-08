#!/usr/bin/env python3

import argparse
import calendar
import datetime
from collections import defaultdict

import pywikibot


DAY_OF_WEEK_START = 6
DAY_OF_WEEK_END = 5
CATEGORY_LABELS = {
    "Category:Draft Episodes": "D",
    "Category:Email Episodes": "E",
    "Category:Guest Episodes": "G",
    "Category:Live Episodes": "L",
    "Category:Patreon Episodes": "P",
}
CALENDAR_INSERT_COMMENT = "<!-- AUTOMATIC CALENDAR -->"

def process_episode(episode_text):
    episode_number = None
    episode_date = None
    for line in episode_text.splitlines():
        if not line.startswith("|"):
            continue
        if "epnumber=" in line:
            _, episode_number = line.split("=")
        elif "date=" in line:
            _, date = line.split("=")
            dt = datetime.datetime.strptime(date, "%B %d, %Y")
            episode_date = dt.date()
    return episode_number, episode_date


def create_calendar_page(site, year):
    year_category = f"{year} Episodes"
    cat = pywikibot.Category(site, year_category)
    episode_labels = {}
    dates = defaultdict(list)
    months = set()
    pages = cat.articles(recurse=False)
    for page in pages:
        episode_number, episode_date = process_episode(page.text)
        date = episode_date.year, episode_date.month, episode_date.day
        dates[date].append(episode_number)
        months.add(episode_date.month)
        episode_label_list = []
        for ep_category in page.categories(content=False):
            cat_title = ep_category.title()
            label = CATEGORY_LABELS.get(cat_title)
            if label:
                episode_label_list.append(label)
        labels = "".join(episode_label_list)
        episode_labels[episode_number] = f"{labels: >1}"

    calendar_lines = [CALENDAR_INSERT_COMMENT]
    cal = calendar.Calendar(DAY_OF_WEEK_START)
    for month in sorted(months):
        dt_day = datetime.date(year, month, 1)
        month_name = dt_day.strftime("%B")
        calendar_lines.append(f"== {month_name} {year} ==")
        calendar_lines.append("")
        calendar_lines.append("{{EpisodeCalendar}}")
        last_dow = 0
        for day, dow in cal.itermonthdays2(year, month):
            if last_dow == DAY_OF_WEEK_END and dow == DAY_OF_WEEK_START:
                calendar_lines.append("|-")
            last_dow = dow
            if day == 0:
                calendar_lines.append("{{EpisodeCalendarDate}}")
                continue
            episodes = dates.get((year, month, day), [])
            episode_info = [f"{episode_labels[episode]}|{episode}" for episode in episodes]
            info = ""
            if episode_info:
                info = "|" + "|\n                         ".join(episode_info)
            calendar_lines.append(f"{{{{EpisodeCalendarDate|{day: >2}{info}}}}}")
        calendar_lines.append("{{EpisodeCalendarEnd}}")
        calendar_lines.append("")
    page_text = "\n".join(calendar_lines)
    return page_text

def options():
    parser = argparse.ArgumentParser()
    parser.add_argument('year', type=int, help="Year to build")
    parser.add_argument('--dry-run', action='store_true', help="Run in dry-run mode")
    parser.add_argument('--rebuild', action='store_true', help="Run full rebuild of calendar")
    args = parser.parse_args()
    return args


def main():
    args = options()

    site = pywikibot.Site('effectivelywild:effectivelywild')
    dry_run_mode = args.dry_run or False
    year = args.year
    page_title = f"{year} Episode Calendar"
    print(f"Checking calendar page {page_title}...")
    if not args.rebuild:
        year_category = f"{year} Episodes"
    else:
        pass

    page = pywikibot.Page(site, page_title)
    if page.exists():
        if CALENDAR_INSERT_COMMENT not in page.text:
            print(f"Error: Could not find '{CALENDAR_INSERT_COMMENT}' in page text, aborting.")
            return
    page_text = create_calendar_page(site, year)
    current_text = page.text
    insert_idx = current_text.index(CALENDAR_INSERT_COMMENT)
    keep_text = current_text[:insert_idx]
    updated_text = keep_text + page_text
    print(page_title)
    print(updated_text)
    page.text = updated_text
    if not dry_run_mode:
        page.save()


if __name__ == '__main__':
    main()
