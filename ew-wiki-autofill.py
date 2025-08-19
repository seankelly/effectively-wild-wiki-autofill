#!/usr/bin/env python3

import argparse
import csv
import datetime
import io
import json
import re
from xml.etree import ElementTree

import bs4
import pywikibot
import requests


EFFECTIVELY_WILD_WIKI = 'https://effectivelywild.fandom.com/wiki/'
EFFECTIVELY_WILD_RSS_URL = 'https://blogs.fangraphs.com/feed/effectively-wild/'
EFFECTIVELY_WILD_EMAIL_CSV_URL = 'https://docs.google.com/spreadsheets/d/1-8lpspHQuR5GK7S_nNtGunLGrx60QnSa8XLG_wvRb4Q/export?gid=0&format=csv'
FEED_NAMESPACES = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "wfw": "http://wellformedweb.org/CommentAPI/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "atom": "http://www.w3.org/2005/Atom",
    "sy": "http://purl.org/rss/1.0/modules/syndication/",
    "slash": "http://purl.org/rss/1.0/modules/slash/",
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
}


class EWEpisode:
    
    def __init__(self, site, check_all=False, test_mode=False):
        self.site = site
        self.test_mode = test_mode
        self.check_all = check_all
        self.state = {}
        self.feed = None
        self.episodes = {}
        self.emails = []

    def load_state(self, state_path):
        with open(state_path) as state_input:
            self.state = json.load(state_input)

    def check_feed(self):
        saved_last_check_time = self.state.get('last_check_time')
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        if saved_last_check_time is None:
            # If no previous check time, assume it was last checked two hours
            # ago and see if it has changed since then.
            last_check_time = now - datetime.timedelta(hours=2)
        else:
            last_check_time = datetime.datetime.fromisoformat(saved_last_check_time)
        # If-Modified-Since: <day-name>, <day> <month> <year> <hour>:<minute>:<second> GMT
        modified_since = last_check_time.strftime('%a, %d %b %Y %H:%M:%S GMT')
        headers = {'If-Modified-Since': modified_since}
        req = requests.get(EFFECTIVELY_WILD_RSS_URL, headers=headers)
        if req.status_code == 200:
            self.feed = ElementTree.fromstring(req.text)
            self._parse_feed()

    def use_local_feed(self, feed_path):
        xml = ElementTree.parse(feed_path)
        self.feed = xml.getroot()
        self._parse_feed()

    def _parse_feed(self):
        self._split_feed()
        episodes = sorted(self.episodes, reverse=True)
        latest_episode = max(episodes)
        # Check which episodes do not yet exist on the wiki page.
        missing_episodes = set()
        for number in episodes:
            if not self._wiki_page_exists(str(number)):
                missing_episodes.add(number)
            elif not self.check_all:
                # Default to only checking until an episode's wiki page exists.
                # When run regularly, this will be the most common situation
                # and saves repeated API calls to confirm older episodes have
                # wiki pages.
                break
        for number in sorted(missing_episodes):
            episode = self.episodes[number]
            episode_title, episode_wikitext = self._parse_episode(number, episode)
            is_latest_episode = number == latest_episode
            if self.test_mode:
                print(episode_title)
                print(episode_wikitext)
            else:
                self._create_episode_pages(number, episode_title, episode_wikitext)

    def _create_episode_pages(self, number, title, page_text):
        # Create the page for the episode.
        page = pywikibot.Page(self.site, title)
        page.text = page_text
        #page.save("Create initial episode page.")
        # Now create the redirect for it.
        redirect = pywikibot.Page(self.site, str(number))
        redirect.text = f"#REDIRECT [[{title}]]"
        #redirect.save("Create redirect to episode page")

    def _wiki_page_exists(self, page_title):
        page = pywikibot.Page(self.site, page_title)
        return page.exists()

    @staticmethod
    def _element_text(element):
        if element is not None:
            return element.text

    @staticmethod
    def _wikify_href(target, anchor_text):
        # Check for FanGraphs player link.
        if (target.startswith('https://www.fangraphs.com/players/') or
            target.startswith('http://www.fangraphs.com/statss.aspx?playerid=')):
            return f"[[{anchor_text}]]"
        elif target.startswith(EFFECTIVELY_WILD_WIKI):
            wiki_page = target[40:].replace('_', ' ')
            return f"[{wiki_page}|{anchor_text}]"
        elif target.startswith('https://en.wikipedia.org/wiki/'):
            wiki_page = target[30:].replace('_', ' ')
            return f"{{{{W|{wiki_page}|{anchor_text}}}}}"
        else:
            return f"[{target} {anchor_text}]"

    def _wikify_link(self, link):
        target = link.get('href')
        anchor_text = link.string
        if target is None:
            return anchor_text
        return self._wikify_href(target, anchor_text)

    def _split_feed(self):
        for item in self.feed.findall('channel/item'):
            # <title>Effectively Wild Episode 2109: And Teoscar Goes To&#8230;</title>
            title = self._element_text(item.find('title'))
            if title is None:
                continue
            description = self._element_text(item.find('content:encoded', FEED_NAMESPACES))
            # Older episodes do not have the description so stop parsing the
            # feed here because only the latest episode is needed.
            if description is None:
                break
            words = title.split()
            episode = words[3].rstrip(':')
            episode_number = int(episode)
            self.episodes[episode_number] = item

    @staticmethod
    def _clean_smart_quotes(text):
        no_smart_dquotes = re.sub(r'[“”]', '"', text)
        no_smart_squotes = re.sub(r'’', "'", no_smart_dquotes)
        return no_smart_squotes

    def _parse_episode(self, number, episode):
        full_title = self._element_text(episode.find('title'))
        # Strip off "Effectively Wild" prefix.
        title = full_title[17:]
        episode_link = self._element_text(episode.find('link'))
        pub_date_text = self._element_text(episode.find('pubDate'))
        pub_date = datetime.datetime.strptime(pub_date_text, '%a, %d %b %Y %H:%M:%S %z')
        description = self._element_text(episode.find('content:encoded', FEED_NAMESPACES))
        duration = self._element_text(episode.find('itunes:duration', FEED_NAMESPACES))
        enclosure = episode.find('enclosure')
        download_url = enclosure.get('url')
        content = bs4.BeautifulSoup(description, 'lxml')
        if content is None:
            return
        links = self._find_links(content)
        audio = self._find_audio_links(content)
        summary = self._find_summary(content)

        hosts = ""
        host_categories = []
        if (summary.startswith("Ben Lindbergh and Meg Rowley") or
            summary.startswith("Ben Lindbergh, Meg Rowley")):
            # Alternate the order of the hosts.
            if number % 2 == 0:
                hosts = "[[Meg Rowley]]<br>[[Ben Lindbergh]]"
            else:
                hosts = "[[Ben Lindbergh]]<br>[[Meg Rowley]]"
            host_categories.extend([
                "[[Category:Ben Lindbergh Episodes]]",
                "[[Category:Meg Rowley Episodes]]",
            ])
        else:
            if 'Ben Lindbergh' in summary:
                host_categories.append("[[Category:Ben Lindbergh Episodes]]")
            if 'Meg Rowley' in summary:
                host_categories.append("[[Category:Meg Rowley Episodes]]")

        emails = self._find_emails(number, summary)

        infobox = [
            "__NOTOC__",
            "{{Episode Infobox",
            "",
            f"| epnumber={number}",
            "",
            f"| title1={title}",
            "",
            f"| infopage={episode_link}",
            "",
            f"| mp3download={download_url}",
            "",
            f"| date={pub_date.strftime('%B')} {pub_date.day}, {pub_date.year}",
            "",
            f"| duration={duration}",
            "",
            f"| hosts={hosts}",
            "",
            f"| intro={audio['intro']}",
            "",
        ]
        for interstitial in audio['inter']:
            infobox.append(f"| interstitials={interstitial}\n")
        infobox.extend([
            f"| outro={audio['outro']}",
            "",
            "}}",
            f"{{{{#vardefine:downloadlink|{download_url}}}}}",
        ])

        links.insert(0, self._wikify_href(episode_link, full_title))
        link_list = [f"* {link}" for link in links]

        wiki_text = '\n'.join(infobox + [
            "{{IncompleteNotice}}",
            "",
            "==Summary==",
            f"''{summary}''",
            "",
            "==Topics==",
            "* {List or summarize the main topics, noting prominently mentioned players or teams"
            " and making internal wiki links to them (even if those pages have not been created"
            " yet).}",
            "",
            "==Banter==",
            "* {- If applicable. For banter, note prominent teams and players, and make internal"
            " links for them.",
            "- Links and mentions do NOT have to be made for players and teams mentioned in passing.}",
            "",
        ] + emails + [
            "==Stat Blast==",
            "* {For STAT BLAST segment: transcribe the scenario that the host is trying to answer"
            " (you do NOT have to transcribe the method used within the Stat Blast, but note its"
            " findings and any other pertinent info.)}",
            "",
            "==Notes==",
            "* {List noteworthy tangents, quotes, highlights, miscellany not covered above.}",
            "",
            "==Links==",
        ] + link_list + [
            "[[Category:Episodes]]",
            "[[Category:Incomplete Episode Page]]",
        ] + host_categories + [
            f"[[Category: {pub_date.year} Episodes]]",
            f"{{{{DEFAULTSORT: Episode 0{number}}}}}",
        ])
        return full_title, self._clean_smart_quotes(wiki_text)

    def _template_latest_episode(self, number, episode):
        full_title = self._element_text(episode.find('title'))
        # Strip off "Effectively Wild" prefix.
        title = full_title[17:]
        episode_link = self._element_text(episode.find('link'))
        wiki_text = "\n".join([
            "{{Latest Episode",
            ""
            f"|epnumber={number}",
            ""
            f"|title1={title}",
            ""
            f"|infopage={episode_link}",
            ""
            """}}<noinclude>This template is the "Latest Episode" banner on the home page. This is a separate transclusion so that it doesn't clutter the history of the home page.</noinclude>""",
        ])
        return wiki_text

    def _find_links(self, description):
        links = []
        for anchor in description.find_all('a'):
            text = anchor.string
            if text is not None and text.startswith('Link'):
                links.append(self._wikify_link(anchor))
        return links

    def _find_audio_links(self, description):
        audio = {
            'intro': None,
            'outro': None,
            'inter': [],
        }
        for paragraph in description.find_all('p'):
            #for child in paragraph.children:
            #    print(f"=> {child}")
            cleaned_text = ''.join(paragraph.stripped_strings)
            # Each audio line will look like:
            #   Audio <what>: Title, Link
            if cleaned_text is not None and cleaned_text.startswith('Audio'):
                text_parts = []
                for child in paragraph.children:
                    if child.name == 'a':
                        text_parts.append(self._wikify_link(child))
                    elif child.string is not None:
                        text_parts.append(child.string)
                text = ''.join(text_parts)
                for line in text.splitlines():
                    idx = line.find(':')
                    if idx == -1:
                        continue
                    audio_text = line[idx + 2:]
                    if 'intro' in line:
                        audio['intro'] = audio_text
                    elif 'outro' in line:
                        audio['outro'] = audio_text
                    else:
                        audio['inter'].append(audio_text)
        return audio

    def _find_summary(self, description):
        def timestamp_replace(match):
            tc = f"({{{{tcl|tc={match.group(1)}}}}})"
            return tc

        summary = []
        timestamp_re = re.compile(r'\((\d+:[\d+:]+)\)')
        paragraphs = description.find_all('p')
        for element in paragraphs[0]:
            text = element.string
            if element.name == 'a':
                summary.append(self._wikify_link(element))
            elif text is not None:
                text = timestamp_re.sub(timestamp_replace, text)
                summary.append(text)
        return ''.join(summary).strip()

    def _load_emails(self):
        emails = []
        emails_db_req = requests.get(EFFECTIVELY_WILD_EMAIL_CSV_URL)
        if 200 <= emails_db_req.status_code < 300:
            email_db_bytes = emails_db_req.content
            emails_db_file = io.StringIO(email_db_bytes.decode(), newline='')
            emails_db = csv.reader(emails_db_file)
            for email in emails_db:
                if email[1] == 'Episode' or email[1] == '':
                    continue
                try:
                    email_episode = int(email[1])
                except ValueError:
                    continue
                self.emails.append((email_episode, email[2]))

    def _find_emails(self, number, content):
        if not self.emails:
            self._load_emails()

        no_emails_found = [
            "==Email Questions==",
            "* {For EMAIL episodes: copy the question and who asked it from the"
            " [https://docs.google.com/spreadsheets/d/1-8lpspHQuR5GK7S_nNtGunLGrx60QnSa8XLG_wvRb4Q/"
            "edit#gid=0 question database],"
            " and link prominent teams and players.}",
            "",
        ]

        emails = []
        for email in self.emails:
            if email[0] == number:
                # Put the blank before the email itself because the emails
                # in the database are "backwards", with the first on the
                # episode the last in the episode list.
                emails.append('')
                emails.append(f"* {email[1].strip()}")
            elif email[0] < number:
                # No more emails for this episode.
                break
        if emails:
            emails.append(no_emails_found[0])
            emails.reverse()

        if not emails:
            return no_emails_found
        return emails


def options():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', metavar='FILE', help="State file")
    parser.add_argument('--rss', metavar='FILE', help="Process local RSS file")
    parser.add_argument('--test', action='store_true', help="Run in test mode")
    parser.add_argument('--all', action='store_true', help="Check all episodes in RSS")
    args = parser.parse_args()
    return args


def main():
    args = options()

    site = pywikibot.Site('effectivelywild:effectivelywild')
    test_mode = args.test or False
    check_all = args.all or False
    effectively_wild = EWEpisode(site, check_all=check_all, test_mode=test_mode)
    if args.rss is not None:
        effectively_wild.use_local_feed(args.rss)
    else:
        effectively_wild.check_feed()


if __name__ == '__main__':
    main()
