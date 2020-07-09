#!/usr/bin/env python3
""" GGSIPU Results Crawler Script """
__version__ = "0.1"

import json
import os
import random
import string
import sys
from io import BytesIO
from logging import DEBUG, INFO, WARNING, Formatter, StreamHandler, getLogger, handlers
from urllib.parse import urljoin

import bs4 as bs
import firebase_admin
from firebase_admin import db as firebase_db
from firebase_admin import storage as firebase_storage
from requests import get

from ggsipu_result import parse_result_pdf, toDict

# OPTION HANDLING


def has_option(name):
    try:
        sys.argv.remove("--%s" % name)
        return True
    except ValueError:
        pass
    # allow passing all cmd line options also as environment variables
    env_val = os.getenv(name.upper().replace("-", "_"), "false").lower()
    if env_val == "true":
        return True
    return False


def option_value(name):
    for index, option in enumerate(sys.argv):
        if option == "--" + name:
            if index + 1 >= len(sys.argv):
                raise Exception("The option %s requires a value" % option)
            value = sys.argv[index + 1]
            sys.argv[index : index + 2] = []
            return value
        if option.startswith("--" + name + "="):
            value = option[len(name) + 3 :]
            sys.argv[index : index + 1] = []
            return value
    env_val = os.getenv(name.upper().replace("-", "_"))
    return env_val


def tryint(i):
    if i is None:
        return None
    try:
        return int(i)
    except ValueError:
        return None


def generate_key(length):
    return "".join(
        random.choice(string.ascii_letters + string.digits) for _ in range(length)
    )


# CONSTANTs and OPTIONs


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.3945.16 Safari/537.36"
}

LOG_LEVEL_CONFIG = {"DEBUG": DEBUG, "INFO": INFO, "WARNING": WARNING}

ROOT = os.path.abspath(os.path.dirname(__file__))

PRODUCTION = has_option("production")
LOG_PATH = option_value("log-path") or "grc.log"
LOG_LEVEL = LOG_LEVEL_CONFIG.get(option_value("log-level")) or DEBUG
LAST_JSON = option_value("last-json") or os.path.join(ROOT, "last", "last.json")
RESULTS_URL = (
    option_value("results-url")
    or "http://164.100.158.135/ExamResults/ExamResultsmain.htm"
)
RESULT_SCRAP_DEPTH = tryint(option_value("scrap-depth")) or 2

OPTION_FORCE_ALL = has_option("force-all")


def setupLogging(logfile, to_file=True):
    logger = getLogger()
    logger.setLevel(DEBUG)

    if to_file:
        # Set up logging to the logfile.
        filehandler = handlers.RotatingFileHandler(
            filename=logfile, maxBytes=5 * 1024 * 1024, backupCount=100
        )
        filehandler.setLevel(LOG_LEVEL)
        fileformatter = Formatter(
            "%(asctime)s %(levelname)-8s: %(funcName)s : %(message)s",
            datefmt="%m/%d/%Y %I:%M:%S %p",
        )
        filehandler.setFormatter(fileformatter)
        logger.addHandler(filehandler)

    # Set up logging to the console.
    streamhandler = StreamHandler()
    streamhandler.setLevel(LOG_LEVEL)
    streamformatter = Formatter("[%(levelname)s] %(funcName)s: %(message)s")
    streamhandler.setFormatter(streamformatter)
    logger.addHandler(streamhandler)

    return logger


def _only_result_tr(tag):
    return (
        tag.name == "tr" and tag.parent.name == "tbody" and tag.td and not tag.td.strong
    )


def _previous_result_td(tag):
    return (
        tag.name == "td"
        and tag.parent.name == "tr"
        and tag.attrs.get("class")
        and "auto-style1" in tag.attrs.get("class")
    )


def scrap_result_tr(tr, base_url):
    tds = tr.find_all("td")
    # Check if only two tds are present
    if len(tds) != 2:
        return None

    # Gets the result title and download link
    notice_a = tds[0].a
    if notice_a:
        notice_txt = notice_a.text
        dwd_url = notice_a.get("href", None)
        if not dwd_url or not notice_txt:
            return None

        notice_date = tds[1].text
        if not notice_date:
            return None

        # Remove newlines, extra whitespaces
        title = " ".join(notice_txt.split())

        return {
            "date": notice_date.strip(),
            "title": title,
            "url": urljoin(base_url, dwd_url.strip()),
        }
    else:
        return None


def scrap_results_pdfs(soup, base_url):
    trs = soup.find_all(_only_result_tr)
    # Discarding
    for tr in trs:
        result_pdf = scrap_result_tr(tr, base_url)
        if result_pdf:
            yield result_pdf


def get_result_pdfs(url=RESULTS_URL, recursive=0):
    logger.debug(f"Scraping pdf from {url} with recursive={recursive}")
    html = get(url, headers=HEADERS).text
    soup = bs.BeautifulSoup(html, "lxml")

    pdfs = list(scrap_results_pdfs(soup, url))
    if recursive > 0:
        next_td = soup.find(_previous_result_td)
        next_href = None
        if (
            (next_td := soup.find(_previous_result_td))
            and (next_td.a)
            and (next_href := next_td.a.attrs.get("href"))
        ):
            next_url = urljoin(url, next_href)
            pdfs += get_result_pdfs(next_url, recursive - 1)
    return pdfs


def download_file(url, html_allow=False, headers=HEADERS, raise_ex=False):
    try:
        resp = get(url, headers=headers)
        if (
            not resp.status_code == 200
            or resp.content is None
            or (("text/html" in resp.headers["Content-Type"]) & (html_allow is False))
        ):
            raise Exception()
        ret = resp.text if html_allow else resp.content
        return ret
    except Exception as ex:
        if raise_ex:
            raise ex
        return None


class BaseDump:
    name = "BaseDump"

    def set_data(self, pdf_info, results=None, subs=None):
        self.pdf_info = pdf_info
        self.results = results
        self.subs = subs
        return self

    def start(self):
        self.dump_results()
        self.dump_subjects()

    def dump_results(self):
        raise NotImplementedError

    def dump_subjects(self):
        raise NotImplementedError

    def _dump_image(self, img, roll_num):
        raise NotImplementedError


class FirebaseDump(BaseDump):
    name = "Firebase"

    def _generate_result_dict(self, result, pdf_info):
        return {
            "examination_name": result.examination_name,
            "marks": toDict(result.marks),
            "semester": result.semester,
            "pdf_info": pdf_info,
        }

    def _process_institutions(self, results):
        inst_dict = {}
        for r in results:
            if r.institution_code and r.institution_name:
                inst_dict[r.institution_code] = r.institution_name
            else:
                logger.warning(
                    f"Not processing Institution as Insufficient data in {toDict(r)}"
                )
        if len(inst_dict) > 0:
            inst_ref = self.ref.child("institutions")
            inst_ref.update(inst_dict)

    def _process_students(self, results):
        update_dict = {}
        for r in results:
            if (
                r.institution_code is not None
                and r.batch is not None
                and r.roll_num is not None
            ):
                base_key = f"{r.institution_code}/{r.batch}/{r.roll_num}"

                update_dict[f"{base_key}/name"] = r.student_name
                update_dict[f"{base_key}/programme_code"] = r.programme_code
                update_dict[f"{base_key}/programme_name"] = r.programme_name
                update_dict[f"{base_key}/batch"] = r.batch
            else:
                logger.warn(f"Not processing Student as Insufficient info in {r}")
        if len(update_dict) > 0:
            stu_ref = self.ref.child("students")
            stu_ref.update(update_dict)
            logger.debug(f"UPDATE Students {update_dict}")

    def _upload_student_image(self, result):
        blob = self.bucket.blob(f'photos/students/{result.roll_num}.jpeg')
        blob.content_type = 'image/jpeg'
        logger.debug(f'Uploading Student image - {blob.name}')
        try:
            img_fp = BytesIO()
            result.image.save(img_fp, format='JPEG')
            blob.upload_from_file(img_fp, rewind=True)
        except Exception as ex:
            logger.exception(str(ex))

    def _process_results(self, results, pdf_info):
        res_dict = {}
        for r in results:
            if (
                r.institution_code is not None
                and r.batch is not None
                and r.roll_num is not None
            ):
                base_ref_addr = f"{r.institution_code}/{r.batch}/{r.roll_num}/results"
                unique_key = generate_key(15)
                res_dict[f"{base_ref_addr}/{unique_key}"] = self._generate_result_dict(
                    r, pdf_info
                )
                if r.image:
                    self._upload_student_image(r)
            else:
                logger.warn(f"Not processing Result as Insufficient info in {r}")
        if len(res_dict) > 0:
            stu_ref = self.ref.child("students")
            stu_ref.update(res_dict)
            logger.debug(f"UPDATE Results {res_dict}")

    def init(self):
        self.app = firebase_admin.initialize_app()
        self.db = firebase_db
        self.ref = firebase_db.reference("server/data")
        self.bucket = firebase_storage.bucket()
        return self

    def dump_results(self):
        if not self.results or not isinstance(self.results, list):
            return
        self._process_institutions(self.results)
        self._process_students(self.results)
        self._process_results(self.results, self.pdf_info)

    def dump_subjects(self):
        if not self.subs or not isinstance(self.subs, dict):
            return
        subs_ref = self.ref.child("subjects")
        if len(self.subs) > 0:
            subs_ref.set(toDict(self.subs))
            logger.debug(f"SET Subjects {toDict(self.subs)}")


def dump_last(pdfinfo):
    os.makedirs(os.path.dirname(LAST_JSON), exist_ok=True)
    with open(LAST_JSON, "w") as fp:
        json.dump(pdfinfo, fp)
        logger.debug(f"Last PDF info saved - {pdfinfo}")


def load_last():
    last = None
    try:
        if LAST_JSON.startswith("{"):
            last = json.loads(LAST_JSON)
        elif os.path.isfile(LAST_JSON):
            with open(LAST_JSON, "r") as fp:
                last = json.load(fp)
    except json.decoder.JSONDecodeError as ex:
        logger.exception(str(ex))

    if last:
        logger.debug(f"Last PDF info loaded - {last}")
    else:
        logger.debug("No Last PDF loaded")
    return last


def new_result_pdfs():
    last = load_last()
    all_pdfs = get_result_pdfs(recursive=RESULT_SCRAP_DEPTH)
    if not last or OPTION_FORCE_ALL:
        return all_pdfs
    else:
        pdfs = []
        for pdf in all_pdfs:
            if pdf != last:
                pdfs.append(pdf)
            else:
                break
        return pdfs


def main(dumps):
    try:
        pdf_infos = new_result_pdfs()
        logger.info(f"{len(pdf_infos)} - New Result PDFs found")
        for i, pdf_info in enumerate(reversed(pdf_infos)):
            logger.info(f"Processing pdf {i+1}/{len(pdf_infos)} - {pdf_info}")
            if pdf := download_file(pdf_info["url"]):
                subs, results = parse_result_pdf(BytesIO(pdf))
                logger.info(
                    f'{len(subs)} Subjects, {len(results)} Results found in {pdf_info["url"]}'
                )
                for dump in dumps:
                    logger.info(f"Dumping into {dump}")
                    dump.set_data(pdf_info, results, subs).start()

                # FIXME:  better logic to save last, refer inu.py
                dump_last(pdf_info)

    except Exception as ex:
        logger.exception(str(ex))


if __name__ == "__main__":
    if PRODUCTION:
        logger = setupLogging(LOG_PATH, False)
        logger.info(f"SCRIPT STARTED (v{__version__}) [ON SERVER]")
    else:
        logger = setupLogging(LOG_PATH, True)
        logger.info(f"SCRIPT STARTED (v{__version__}) [LOCAL]")

    dumps = [
        FirebaseDump().init(),
    ]
    logger.info(f"Crawler Dumps - {dumps}")
    main(dumps)
    logger.info(f"SCRIPT ENDED (v{__version__}) {os.linesep}")
