"""
update_metadata_recovered.py
Update metadata.csv for the 39 entries recovered in the 47-failed-downloads pass.

For each recovered file_id where raw/{file_id}.pdf now exists:
  - Set source_url to the new working URL (where it changed)
  - Set date_added = today
  - Strip the prior 'Download failed: ...' note
  - Add a short recovery provenance note where applicable
"""
import csv
import re
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "raw"
METADATA = REPO_ROOT / "metadata.csv"

TODAY = "2026-05-29"

# file_id -> (new_url_or_None, recovery_note_or_None)
# None for new_url means keep existing URL.
RECOVERIES = {
    # Phase 1: requests-with-browser-headers (URL unchanged; was bot-blocked)
    "bgd_2013_national_strategy_for_the_development_of": (None, None),
    "bwa_2015_botswana_strategy_for_the_development_of": (None, None),
    "cod_2012_stratégie_nationale_de_développement_de": (None, None),
    "gnb_2018_stratégie_nationale_de_développement_de": (None, None),
    "jor_2018_national_strategy_for_development_of_sta": (None, None),
    "lby_2018_national_strategy_for_the_development_of": (None, None),
    "mmr_2016_national_strategy_for_the_development_of": (None, None),
    "sle_2022_extended_second_national_strategy_for_th": (None, None),
    "syc_2023_national_strategic_plan_for_statistics_2": (None, None),
    "ton_2019_tonga_strategy_for_development_of_statis": (None, None),
    "vnm_2011_vietnam_statistical_development_strategy": (None, None),
    "zwe_2021_national_strategy_for_the_development_of": (None, None),
    # Phase 2: curl pass (URL unchanged; TLS-fingerprint blocked Python)
    "ken_2023_national_strategy_for_the_development_of": (None, None),
    "ken_2023_strategic_plan_2023_2027": (None, None),
    "sen_2019_troisieme_stratégie_nationale_de_dévelop": (None, None),
    "uga_2020_third_plan_for_national_statistical_deve": (None, None),
    "ury_2022_plan_estadístico_nacional_20222025": (None, None),
    # Phase 3: original URL worked via Python where curl failed
    "bra_2017_plano_estratégico_2017_2027": (None, None),
    # Phase 4: replacement URLs via web search
    "bdi_2016_stratégie_nationale_du_développement_de": (
        "https://afristat.org/wp-content/uploads/2022/04/3_Burundi_Document-Principal-2-2016-2020.pdf", None),
    "gha_2018_national_strategy_for_the_development_of": (
        "https://www.paris21.org/sites/default/files/Ghana%20NSDS%202.pdf", None),
    "nam_2023_national_strategy_for_the_development_of": (
        "https://nsa.org.na/wp-content/uploads/2024/06/NSDS-Report.pdf", None),
    "mwi_2019_national_statistical_system_strategic_pl": (
        "https://cms.nsomalawi.mw/api/download/407/National-Statistical-System-Strategic-Plan-2019-2023.pdf", None),
    "rwa_2024_national_strategy_for_the_development_of": (
        "https://www.statistics.gov.rw/sites/default/files/documents/2025-05/NSDS4%20(2024_2029).pdf", None),
    "eth_2021_national_strategy_for_the_development_of": (
        "https://mopd.gov.et/media/data-documents/ETHIOPIAN_STATISTICAL_DEVELOPMENT_PROGRAM.pdf", None),
    "gnq_2022_estrategia_nacional_de_desarrollo_de_la": (
        "https://inege.org/wp-content/uploads/2023/09/ENDE-2022-2026-1.pdf", None),
    "som_2024_national_strategy_for_the_development_of": (
        "https://nbs.gov.so/wp-content/uploads/2025/12/Somalia-NSDS.pdf", None),
    "rus_2019_2024_rosstat_development_strategy_strate": (
        "https://eng.rosstat.gov.ru/storage/mediabank/Strategy%202024.pdf", None),
    "mlt_2023_national_statistics_office_work_programm": (
        "https://nso.gov.mt/wp-content/uploads/Work-Programme_2023-2025-1.pdf", None),
    "mex_2019_programa_nacional_de_estadística_y_geogr": (
        "https://www.snieg.mx/Documentos/Programas/PNEG_2019-2024_Actualizacion-2023.pdf", None),
    "bol_2021_plan_estratgégico_institucional_pei_2021": (
        "https://www.ine.gob.bo/index.php/descarga/277/planes-estrategicos-institucionales/65534/pei-del-ine-2021-2025-2-version.pdf", None),
    "mys_2021_pelan_strategik_jabatan_perangkaan_malay": (
        "https://www.dosm.gov.my/portal-main/publication-log?document_id=9&chapter_id=126&chapter_type=pdf", None),
    "ken_gender_stats_plan": (
        "https://www.knbs.or.ke/wp-content/uploads/2023/09/Gender-Sector-Statistics-Plan.pdf", None),
    # Phase 5: Wayback Machine (live URL dead/blocked; archive served the file)
    "rou_2021_the_national_statistical_system_developm": (None, "Recovered from Wayback Machine; live URL is Cloudflare-blocked"),
    "idn_2020_national_statistical_plan_2020_2024": (None, "Recovered from Wayback Machine; live URL is Cloudflare-blocked"),
    "qat_2008_national_strategy_for_the_development_of": (None, "Recovered from Wayback Machine; live URL is dead"),
    "vut_2024_national_strategy_for_the_development_of": (None, "Recovered from Wayback Machine; live URL returns 404"),
    "npl_2018_national_strategy_for_the_development_of": (None, "Recovered from Wayback Machine; live host unreachable"),
    "aut_noyr_statistical_work_program_2021_2024": (None, "Recovered from Wayback Machine; live host unreachable"),
    "phl_2023_philippine_statistical_development_progr": (
        "https://psa.gov.ph/sites/default/files/infographics/PSDP%202023-2029%20Primer_rev-2811.pdf",
        "Recovered from Wayback Machine; live host is WAF-blocked"),
}


def strip_failed_note(note):
    if not note:
        return ""
    note = re.sub(r"Download failed[^;]*;?\s*", "", note).strip()
    return note.strip(" ;")


def main():
    with open(METADATA, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        fieldnames = rdr.fieldnames
        rows = list(rdr)

    by_id = {r["file_id"]: r for r in rows}
    updated, missing_files = [], []
    for fid, (new_url, note) in RECOVERIES.items():
        if fid not in by_id:
            print(f"  WARN file_id not in metadata: {fid}")
            continue
        if not (RAW / f"{fid}.pdf").exists():
            missing_files.append(fid)
            continue
        r = by_id[fid]
        if new_url:
            r["source_url"] = new_url
        r["date_added"] = TODAY
        cleaned = strip_failed_note(r.get("notes", ""))
        if note:
            r["notes"] = (cleaned + ("; " if cleaned else "") + note).strip()
        else:
            r["notes"] = cleaned
        updated.append(fid)

    with open(METADATA, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Updated metadata for {len(updated)} recovered file_ids.")
    if missing_files:
        print(f"  PDF missing for {len(missing_files)}: {missing_files}")


if __name__ == "__main__":
    main()
