# GDELT daily event summaries

`tradingagents.dataflows.vendors.gdelt_events.render_gdelt_events(decision_time, cache)`
returns a compact summary for the UTC calendar day two days before the supplied
timezone-aware decision timestamp. Supply a dictionary shared only by the current
run as `cache` to avoid downloading the same daily file for multiple assets.

GDELT 1.0 daily files contain tab-separated, CAMEO-coded event records. The
summary reports record counts by quadrant, the mean reported news tone, the file
date and its SHA256. Counts are records, not verified unique events. Media tone
is not an investment recommendation, and this archive is neither a complete
news archive nor historical Reddit or Stocktwits sentiment.

The two-day lag is a **simulation assumption**, not a verified publication
timestamp. `DATEADDED` in these files has day precision and does not prove when
the archive was publicly accessible. A current download also cannot prove that
the archive has not been revised since the decision. The summary labels these
limits; it must not be described as verified point-in-time coverage. If the
file, timestamps or size cannot be validated, the function fails instead of
substituting another day or assuming that there were no events.

The official daily event format began on 2013-04-01. See the [GDELT data
codebook](https://data.gdeltproject.org/documentation/GDELT-Data_Format_Codebook.pdf)
and [daily archive](https://data.gdeltproject.org/events/).
