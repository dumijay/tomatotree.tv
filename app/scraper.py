import sys
import json
import sqlite3
import urllib

import aiohttp
import asyncio
import requests

from bs4 import BeautifulSoup
from tqdm import tqdm
from yarl import URL

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"

urlmap_db = sqlite3.connect("urlmap.db")
urlmap_cursor = urlmap_db.cursor()
delay_per_request = 0.1

rt_db = sqlite3.connect("rt.db")
rt_cursor = rt_db.cursor()

proxy = None

if len(sys.argv) > 1:
    proxy = sys.argv[1]


try:
    urlmap_cursor.execute(
        """
        CREATE TABLE urlmap (
            name text unique,
            url text
        )
    """
    )
except sqlite3.OperationalError:
    pass

try:
    rt_cursor.execute(
        """
        CREATE TABLE series (
            url TEXT UNIQUE,
            name TEXT,
            image TEXT,
            genre TEXT,
            network TEXT,
            year INT,
            tomatometer_score INT,
            audience_score INT
        )
    """
    )
except sqlite3.OperationalError:
    pass


def generate_urlmap():
    def map_exists(show_name):
        urlmap_cursor.execute(f"select count(*) from urlmap where name='{show_name}';")
        results = urlmap_cursor.fetchall()[0][0] > 0
        return results

    show_names = []

    print("Getting series names from Epguides...")
    for letter in tqdm(
        [
            "a",
            "b",
            "c",
            "d",
            "e",
            "f",
            "g",
            "h",
            "i",
            "j",
            "k",
            "l",
            "m",
            "n",
            "o",
            "p",
            "q",
            "r",
            "s",
            "t",
            "u",
            "v",
            "w",
            "x",
            "y",
            "z",
        ]
    ):
        page = requests.get(f"http://epguides.com/menu{letter}/")
        soup = BeautifulSoup(page.content, "html.parser")
        links = soup.select(".cont a")
        for link in links:
            show_name = link.text.replace("'", "")
            if not map_exists(show_name):
                show_names.append(show_name)

    pbar = tqdm(show_names)

    async def get_url(show_name, session):
        pbar.set_description(show_name)
        url = (
            "https://www.rottentomatoes.com/napi/search/all?type=tv&searchQuery="
            + urllib.parse.quote(show_name)
        )
        try:
            async with session.get(
                url, headers={"User-Agent": USER_AGENT}, proxy=proxy
            ) as response:
                result = await response.json()
                tvs = result.get("tv")
                items = tvs.get("items")
                if len(items) > 0:
                    item = items[0]
                    url = item["url"].replace("'", "''")
                    urlmap_cursor.execute(
                        f"""
                        INSERT INTO urlmap VALUES (
                            '{show_name}',
                            '{url}'
                        )
                    """
                    )
                    urlmap_db.commit()
                pbar.update(1)
        except Exception as e:
            print(show_name, url, e)

    async def get_urls():
        async with aiohttp.ClientSession() as client:
            tasks = []
            for show_name in show_names:
                tasks.append(
                    asyncio.ensure_future(
                        get_url(
                            show_name,
                            client,
                        )
                    )
                )
                await asyncio.sleep(delay_per_request)
            await asyncio.gather(*tasks)

    print("Getting Rotten Tomatoes URLs for series...")
    asyncio.run(get_urls())


def extract_data_from_urls():
    print("Scraping data from from Rotten Tomatoes...")
    urls = []
    urlmap_cursor.execute(f"select url from urlmap")
    results = urlmap_cursor.fetchall()
    for r in results:
        urls.append(r[0])
    urls = list(dict.fromkeys(urls))
    urls = [url for url in urls if not url_exists(url)]
    pbar = tqdm(urls)

    def url_exists(url):
        rt_cursor.execute(
            f"""select count(*) from series where url='{url.replace("'","''")}';"""
        )
        return rt_cursor.fetchall()[0][0] > 0

    def extract_rt_data(html):
        soup = BeautifulSoup(html, "html.parser")
        name = soup.select("[data-qa='score-panel-series-title']")[0].text.strip()
        try:
            image = soup.select("[data-qa='poster-image']")[0].get("src")
        except:
            image = ""
        try:
            genre = soup.select("[data-qa='series-details-genre']")[0].text.strip()
        except:
            genre = ""
        try:
            network = soup.select("[data-qa='series-details-network']")[0].text.strip()
        except:
            network = ""
        try:
            year = soup.select("[data-qa='series-details-premiere-date']")[
                0
            ].text.split()[-1]
        except:
            year = 0
        try:
            tomatometer_score = (
                soup.select("[data-qa='tomatometer']")[0].text.strip().replace("%", "")
            )
        except:
            tomatometer_score = 0
        try:
            audience_score = (
                soup.select("[data-qa='audience-score']")[0]
                .text.strip()
                .replace("%", "")
            )
        except:
            audience_score = 0
        if tomatometer_score == 0 and audience_score == 0:
            raise Exception("Missing score")
        return dict(
            name=name,
            image=image,
            genre=genre,
            network=network,
            year=year,
            tomatometer_score=tomatometer_score,
            audience_score=audience_score,
        )

    async def scrape_url(url, session):
        pbar.set_description(url)
        try:
            async with session.get(
                url, headers={"User-Agent": USER_AGENT}, proxy=proxy
            ) as response:
                result = await response.text()
                pbar.update(1)
                item = None
                try:
                    item = extract_rt_data(result)
                except:
                    pass
                if not item:
                    return
                url = url.replace("'", "''")
                name = (
                    f"""'{item['name'].replace("'","''")}'"""
                    if item["name"]
                    else "NULL"
                )
                image = f"'{item['image']}'" if item["image"] else "NULL"
                genre = f"'{item['genre']}'" if item["genre"] else "NULL"
                network = (
                    f"""'{item['network'].replace("'","''")}'"""
                    if item["network"]
                    else "NULL"
                )
                year = f"{item['year']}" if item["year"] else "NULL"
                tomatometer_score = (
                    f"{item['tomatometer_score']}"
                    if item["tomatometer_score"]
                    else "NULL"
                )
                audience_score = (
                    f"{item['audience_score']}" if item["audience_score"] else "NULL"
                )
                rt_cursor.execute(
                    f"""
                    INSERT INTO series VALUES (
                        '{url}',
                        {name},
                        {image},
                        {genre},
                        {network},
                        {year},
                        {tomatometer_score},
                        {audience_score}
                    )
                """
                )
                rt_db.commit()
        except Exception as e:
            print(url, e)

    async def scrape_urls():
        async with aiohttp.ClientSession() as client:
            tasks = []
            for url in urls:
                if url_exists(url):
                    continue
                tasks.append(
                    asyncio.ensure_future(
                        scrape_url(
                            url,
                            client,
                        )
                    )
                )
                await asyncio.sleep(delay_per_request)
            await asyncio.gather(*tasks)

    asyncio.run(scrape_urls())


if __name__ == "__main__":
    generate_urlmap()
    extract_data_from_urls()
