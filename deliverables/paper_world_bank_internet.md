# Internet Diffusion Across Countries, 2010–2022: An Exploratory Country-Year Analysis

**稿件状态：** exploratory manuscript / preliminary revision draft  
**数据来源：** World Bank, World Development Indicators  
**分析脚本：** `analysis/world_bank_internet_country.py`  
**数据回执：** `deliverables/analysis_receipt.json`

## Abstract

### English

This exploratory study examines the association between calendar year and the share of individuals using the Internet across countries from 2010 to 2022. Data were retrieved from the World Bank World Development Indicators series `IT.NET.USER.ZS`, which is sourced from the International Telecommunication Union. Country-level observations were separated from World Bank aggregate entities using the country metadata endpoint. The screened dataset contained 2,821 country-year rows from 217 countries; 2,531 observations had non-missing Internet-use values. A Pearson correlation between year and Internet use was positive and statistically precise in the unadjusted country-year data, *r* = .376, 95% CI [.34, .41], *p* < .001. The estimate is descriptive rather than causal: repeated observations within countries, unequal country coverage, missing values, measurement revisions, and temporal dependence prevent the reported *p* value from being interpreted as an independent-observation test. The manuscript therefore treats the result as a reproducible descriptive signal and specifies a country-clustered panel model as the next confirmatory analysis.

**Keywords:** Internet adoption; digital inequality; World Development Indicators; country-year panel; exploratory analysis

### 中文摘要

本文考察 2010—2022 年各国互联网使用率与年份之间的描述性关联。数据取自世界银行世界发展指标数据库中的 `IT.NET.USER.ZS` 指标，该指标来源于国际电信联盟。研究依据世界银行国家元数据，将国家观测与区域、收入组等汇总实体分离。筛选后数据包含 217 个国家的 2,821 个国家—年份观测，其中 2,531 条具有非缺失互联网使用率。未调整的 Pearson 相关显示年份与互联网使用率呈正相关，*r* = .376，95% CI [.34, .41]，*p* < .001。该结果仅是描述性证据，不能作因果解释；同一国家的重复观测、国家覆盖不均衡、缺失值、指标修订和时间依赖都会影响独立观测假设。因此，本文将该结果定位为可复现的探索性信号，并把国家聚类的面板模型列为后续确证分析。

**关键词：** 互联网使用率；数字不平等；世界发展指标；国家—年份面板；探索性分析

## 1. Introduction

Internet access is a central dimension of contemporary social and economic participation, but its expansion is uneven across countries and over time. A first empirical question is whether the country-year distribution of Internet use shows a systematic temporal pattern during the period in which Internet adoption became widespread. This paper provides a transparent, reproducible first analysis of that question using an openly available international indicator.

The study is intentionally narrow. It estimates an unconditional association between calendar year and the percentage of individuals using the Internet. It does not identify the causes of digital expansion, compare policy regimes, or estimate a causal effect. The contribution is methodological and empirical: the analysis documents a clear data-screening rule, preserves the original download, records the exact analysis environment and output, and separates an exploratory association from a future confirmatory panel design.

## 2. Data and Method

### 2.1 Data source and indicator

The data were downloaded from the World Bank API for indicator `IT.NET.USER.ZS`, “Individuals using the Internet (% of population),” for 2010–2022. The World Bank page identifies the International Telecommunication Union as the source and provides the indicator under a CC BY-4.0 license ([World Bank, n.d.-a](https://data.worldbank.org/indicator/IT.NET.USER.ZS)). World Development Indicators documentation cautions that international and intertemporal comparisons may be affected by differences in availability, reporting practice, definitions, and revisions ([World Bank, n.d.-b](https://datatopics.worldbank.org/world-development-indicators/sources-and-methods.html)).

The initial download contained 3,445 rows. The raw file is preserved as `data/clean/world_bank_internet.csv` together with the download URL and SHA-256 hash in the run receipt. Because the API response includes regional and other aggregate entities, country metadata were queried from the World Bank API and observations whose region was labeled “Aggregates” were excluded. The screened file is `data/clean/world_bank_internet_country.csv`.

### 2.2 Variables and analytic sample

The outcome was the reported percentage of individuals using the Internet (`value`). The predictor was calendar year (`year`). The screened dataset contained 2,821 country-year rows representing 217 countries. Of these, 2,531 rows had non-missing outcome values; 290 rows were excluded from the correlation calculation because the outcome was missing or not parseable. No interpolation or imputation was performed.

### 2.3 Statistical analysis

The supplied PsyClaw analysis script computed a Pearson product-moment correlation between `year` and `value` after pairwise exclusion of missing values. The script reports the correlation, a 95% confidence interval, a two-sided *p* value, and a software-reported power field. The confidence interval and *p* value are conditional on the simple correlation model and should not be treated as a final panel-data inference. In particular, observations from the same country are repeated over time, so the independence assumption is not credible for confirmatory inference.

All transformations and execution were performed by `analysis/world_bank_internet_country.py`. The tool execution returned exit code 0 and wrote a structured receipt; no numerical result was manually entered into this manuscript.

## 3. Results

### 3.1 Data screening

The raw download contained 3,445 rows and 563 missing cells across the five downloaded columns. After removing World Bank aggregate entities, 2,821 country-year rows remained. The screened sample covered 217 countries and 2010–2022. The analysis used 2,531 complete country-year observations for `year` and Internet use.

### 3.2 Exploratory association

Internet use was positively associated with calendar year in the unadjusted country-year data, *r* = .376, 95% CI [.34, .41], *p* < .001, *N* = 2,531. The corresponding script output also reported a power value of 1.00; because this calculation treats the rows as independent, it should be read as a property of the simplified correlation calculation rather than evidence that the study has adequate power for a clustered panel design.

The estimate is substantively consistent with a broad upward temporal pattern in Internet adoption, but the design does not distinguish a common time trend from country-specific change, cohort composition, reporting changes, or other concurrent processes.

## 4. Discussion

The main result is a reproducible positive descriptive association between year and Internet use in the screened World Bank country-year data. The result is useful as a data audit and as a starting point for a stronger panel analysis. It does not show that the passage of time caused Internet adoption, nor does it identify which policies, economic conditions, infrastructure investments, or demographic processes account for the association.

The screening step materially changes the estimand. The raw API response included aggregate entities, whose values are constructed using World Bank aggregation procedures and should not be treated as additional countries. The paper therefore reports the country-only estimate as the primary exploratory result and retains the raw result only as an audit trail.

## 5. Limitations and Confirmatory Analysis Plan

First, the current analysis treats repeated country-year observations as independent. A confirmatory version should use a country-clustered panel model, such as a regression of Internet use on year with country fixed effects and year fixed effects or a parsimonious trend specification. Standard errors should be clustered by country, and the analysis should report the number of countries, within-country observations, missingness by year, and sensitivity to unbalanced panels.

Second, the World Bank documentation notes limitations in international comparability, data availability, reporting practices, and revisions. Third, missing outcomes are not necessarily random. Fourth, a linear Pearson association may obscure nonlinear diffusion, ceiling effects, and heterogeneous trajectories. Finally, this single-indicator design contains no covariates and cannot support causal claims.

## 6. Data, Code, and Reproducibility

The raw API extract is stored at `data/clean/world_bank_internet.csv`; the country-screened analysis file is `data/clean/world_bank_internet_country.csv`. The executable analysis is `analysis/world_bank_internet_country.py`. The structured execution receipt is `deliverables/analysis_receipt.json`, which records the input hash, sample profile, analysis recommendation, return code, and exact stdout. The data are publicly available from the World Bank under the source and license information provided on the indicator page.

## 7. Ethics, Funding, Conflicts, and AI Disclosure

**Ethics.** This study uses publicly available, aggregate country-level data and does not involve human participants, personal data, or intervention.

**Funding.** No external funding was recorded for this analysis.

**Conflict of interest.** The authors declare no conflicts of interest.

**Author contributions.** Data curation, analysis, and manuscript drafting should be assigned to named human authors before submission. PsyClaw was used as a computational orchestration and drafting aid; it is not an author and does not replace human responsibility for the analysis, interpretation, or final text.

**AI disclosure.** PsyClaw generated the reproducible analysis scaffold, executed the registered script, and assisted with manuscript organization. The numerical results in this manuscript were copied from the structured execution receipt and should be independently checked by the submitting authors before publication.

## References

World Bank. (n.d.-a). *Individuals using the Internet (% of population)*. World Development Indicators. https://data.worldbank.org/indicator/IT.NET.USER.ZS

World Bank. (n.d.-b). *World Development Indicators: Sources and methods*. https://datatopics.worldbank.org/world-development-indicators/sources-and-methods.html

World Bank. (n.d.-c). *Metadata API queries*. Data Help Desk. https://datahelpdesk.worldbank.org/knowledgebase/articles/1886695-metadata-api-queries

International Telecommunication Union. (n.d.). *ITU datahub*. https://datahub.itu.int/

## Appendix A. PsyClaw Execution Record

```text
Input: data/clean/world_bank_internet_country.csv
Script: analysis/world_bank_internet_country.py
Return code: 0
Complete observations: N = 2,531
Pearson r: 0.375532
95% CI: [0.34, 0.41]
p value: 1.392456e-85
```

