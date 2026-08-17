# -*- coding: utf-8 -*-
"""
ETF Quant LIVE ACTIVE12 FINAL OOS - weekly signal engine

V5.4 운용 규칙과 동일한 주봉 신호만 계산합니다.
- ACTIVE 12
- RSI14(SMA)
- SMA20 weekly
- OBV + 9-week signal
- MACD 12/26/9, loose = MACD >= signal OR MACD > 0
- BOTTOM: previous RSI <= 30, current close < SMA20, bullish weekly candle
- TREND: close > SMA20, OBV >= OBV signal, MACD loose
- 신규 후보 우선순위: TREND 우선, 같은 유형은 strength 높은 순
- 중복 ETF 4종 제거: 반도체/2차전지산업/미국배당다우존스/미국빅테크TOP7 Plus

이 파일은 주문을 실행하지 않습니다. 최신 완료 주봉 신호를 data/latest_signals.json으로 생성합니다.
"""
from __future__ import annotations

import json, math, time, sys
from pathlib import Path
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception:
    yf = None
try:
    import FinanceDataReader as fdr
except Exception:
    fdr = None

KST = ZoneInfo('Asia/Seoul')

UNIVERSE = {
    '069500.KS': 'KODEX 200',
    '229200.KS': 'KODEX 코스닥150',
    '133690.KS': 'TIGER 미국나스닥100',
    '360750.KS': 'TIGER 미국S&P500',
    '245340.KS': 'TIGER 미국다우존스30',
    '466920.KS': 'SOL 조선TOP3플러스',
    '449450.KS': 'PLUS K방산',
    '487240.KS': 'KODEX AI전력핵심설비',
    '305540.KS': 'TIGER 2차전지테마',
    '139260.KS': 'TIGER 200 IT',
    '157500.KS': 'TIGER 200 증권',
    '091180.KS': 'KODEX 자동차',
}
THEME_GROUP = {}

RSI_BOTTOM = 30.0
RSI_WAIT = 33.0
SMA_WINDOW = 20
RSI_WINDOW = 14
OBV_SIGNAL_WINDOW = 9
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9


def code6(ticker:str)->str:
    return ticker.split('.')[0]


def clean_ohlcv(df:pd.DataFrame)->pd.DataFrame:
    if df is None or len(df)==0: return pd.DataFrame()
    x=df.copy()
    if isinstance(x.columns,pd.MultiIndex):
        # yfinance 단일 ticker에서도 MultiIndex가 나올 수 있음
        x.columns=x.columns.get_level_values(0)
    ren={}
    for c in x.columns:
        s=str(c).strip().lower()
        if s in ('open','시가'): ren[c]='Open'
        elif s in ('high','고가'): ren[c]='High'
        elif s in ('low','저가'): ren[c]='Low'
        elif s in ('close','종가','adj close','adjclose'): ren[c]='Close'
        elif s in ('volume','거래량'): ren[c]='Volume'
    x=x.rename(columns=ren)
    needed=['Open','High','Low','Close']
    if not all(c in x.columns for c in needed): return pd.DataFrame()
    if 'Volume' not in x.columns: x['Volume']=0.0
    x=x[['Open','High','Low','Close','Volume']].copy()
    x.index=pd.to_datetime(x.index,errors='coerce')
    x=x[~x.index.isna()]
    try:
        if x.index.tz is not None: x.index=x.index.tz_convert(None)
    except Exception: pass
    for c in x.columns: x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x[~x.index.duplicated(keep='last')].sort_index().dropna(subset=needed)
    x=x[(x.Open>0)&(x.High>0)&(x.Low>0)&(x.Close>0)]
    return x


def fetch_with_retry(fn, tries=3):
    err=None
    for k in range(tries):
        try:
            d=clean_ohlcv(fn())
            if not d.empty: return d, None
            err='empty'
        except Exception as e:
            err=repr(e)
        time.sleep(1.0*(k+1))
    return pd.DataFrame(), err


def download_daily(ticker:str):
    """V5 계열과 비슷하게 FDR-NAVER + Yahoo 중 긴/신선한 데이터를 선택."""
    candidates=[]; errors=[]
    c=code6(ticker)
    if fdr is not None:
        d,e=fetch_with_retry(lambda: fdr.DataReader(f'NAVER:{c}', '2000'),2)
        if not d.empty: candidates.append(('fdr_naver',d))
        elif e: errors.append('fdr_naver:'+str(e))
    if yf is not None:
        d,e=fetch_with_retry(lambda: yf.download(ticker,period='max',interval='1d',progress=False,auto_adjust=True,actions=False,threads=False),2)
        if not d.empty: candidates.append(('yf_daily_max',d))
        elif e: errors.append('yf:'+str(e))
    if not candidates:
        raise RuntimeError(' | '.join(errors) or 'no data source')
    # LIVE는 백테스트 최대기간보다 '최신 거래일'을 우선한다.
    # 최신 거래일까지 동일한 후보들 중 가장 긴 이력을 선택한다.
    latest_end=max(pd.Timestamp(d.index.max()).normalize() for _,d in candidates)
    fresh=[item for item in candidates if pd.Timestamp(item[1].index.max()).normalize()==latest_end]
    source,d=max(fresh,key=lambda item:(pd.Timestamp(item[1].index.max())-pd.Timestamp(item[1].index.min())).days)
    return d.copy(), source, errors


def completed_daily(df:pd.DataFrame)->pd.DataFrame:
    """주중 수동 실행 시 미완성 현재 주를 제거. 금요일 장 마감 후/주말에는 현재 주 포함."""
    x=clean_ohlcv(df)
    if x.empty: return x
    now=datetime.now(KST)
    today=pd.Timestamp(now.date())
    monday=today-pd.Timedelta(days=today.weekday())
    include_current = now.weekday()>4 or (now.weekday()==4 and now.time()>=dtime(16,10))
    if include_current:
        return x[x.index<=today].copy()
    return x[x.index<monday].copy()


def daily_to_weekly(df:pd.DataFrame)->pd.DataFrame:
    d=completed_daily(df)
    if d.empty:return d
    return d.resample('W-FRI',label='right',closed='right').agg(
        {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}
    ).dropna(subset=['Open','High','Low','Close'])


def rsi_sma(close:pd.Series,window=14):
    delta=close.diff(); gain=delta.clip(lower=0.0); loss=(-delta.clip(upper=0.0))
    ag=gain.rolling(window).mean(); al=loss.rolling(window).mean(); rs=ag/(al+1e-12)
    return 100-100/(1+rs)


def indicators(w:pd.DataFrame)->pd.DataFrame:
    x=w.copy()
    x['SMA20']=x.Close.rolling(SMA_WINDOW).mean()
    x['RSI']=rsi_sma(x.Close,RSI_WINDOW)
    direction=np.sign(x.Close.diff()).fillna(0.0)
    x['OBV']=(direction*x.Volume.fillna(0.0)).cumsum()
    x['OBV_Signal']=x.OBV.rolling(OBV_SIGNAL_WINDOW).mean()
    ef=x.Close.ewm(span=MACD_FAST,adjust=False).mean(); es=x.Close.ewm(span=MACD_SLOW,adjust=False).mean()
    x['MACD']=ef-es; x['MACD_Signal']=x.MACD.ewm(span=MACD_SIGNAL,adjust=False).mean(); x['MACD_Hist']=x.MACD-x.MACD_Signal
    x['Is_Bullish']=x.Close>x.Open
    return x


def row_valid(w,i):
    if i<1 or i>=len(w): return False
    cols=['SMA20','RSI','OBV_Signal','MACD','MACD_Signal']
    return not w.iloc[i][cols].isna().any() and not pd.isna(w.iloc[i-1].RSI)


def signal_at(w,i):
    if not row_valid(w,i): return None
    c=w.iloc[i]; p=w.iloc[i-1]
    bottom=bool(p.RSI<=RSI_BOTTOM and c.Close<c.SMA20 and c.Is_Bullish)
    if bottom:
        body=max((c.Close/max(c.Open,1e-12)-1)*100,0)
        strength=max(RSI_BOTTOM-float(p.RSI),0)+body
        return {'type':'BOTTOM','support':float(p.Low),'strength':float(strength),
                'reason':f'직전 RSI({p.RSI:.1f})<=30 + 20주선 아래 + 완료주봉 양봉'}
    macd_ok=bool((c.MACD>=c.MACD_Signal) or (c.MACD>0))
    trend=bool(c.Close>c.SMA20 and c.OBV>=c.OBV_Signal and macd_ok)
    if trend:
        dist=max((c.Close/c.SMA20-1)*100,0)
        hist=max(c.MACD_Hist/max(abs(c.Close),1e-12)*100,0)
        return {'type':'TREND','support':None,'strength':float(dist+hist),
                'reason':'20주선 위 + OBV 강세 + MACD(loose)'}
    return None


def fnum(x,digits=6):
    try:
        if x is None or not np.isfinite(float(x)): return None
        return round(float(x),digits)
    except Exception:return None


def analyze_one(ticker,name):
    d,source,errors=download_daily(ticker)
    w=indicators(daily_to_weekly(d))
    if len(w)<35: raise RuntimeError(f'weekly bars too short: {len(w)}')
    i=len(w)-1
    if not row_valid(w,i): raise RuntimeError('latest weekly indicator not ready')
    sig=signal_at(w,i)
    psig=signal_at(w,i-1) if i>0 and row_valid(w,i-1) else None
    is_new=bool(sig is not None and (psig is None or psig.get('type')!=sig.get('type')))
    c=w.iloc[i]; p=w.iloc[i-1]
    wait=bool(sig is None and (c.RSI<=RSI_WAIT or p.RSI<=RSI_BOTTOM))
    return {
      'ticker':ticker,'code':code6(ticker),'name':name,'theme_group':THEME_GROUP.get(ticker,ticker),
      'source':source,'source_errors':errors,'data_start':str(pd.Timestamp(d.index.min()).date()),
      'data_end':str(pd.Timestamp(d.index.max()).date()),'weekly_date':str(pd.Timestamp(w.index[i]).date()),
      'close':fnum(c.Close,4),'open':fnum(c.Open,4),'high':fnum(c.High,4),'low':fnum(c.Low,4),
      'sma20':fnum(c.SMA20,4),'rsi':fnum(c.RSI,3),'prev_rsi':fnum(p.RSI,3),
      'obv':fnum(c.OBV,2),'obv_signal':fnum(c.OBV_Signal,2),'macd':fnum(c.MACD,6),
      'macd_signal':fnum(c.MACD_Signal,6),'macd_hist':fnum(c.MACD_Hist,6),'bullish':bool(c.Is_Bullish),
      'signal':sig.get('type') if sig else None,'signal_strength':fnum(sig.get('strength'),6) if sig else None,
      'signal_reason':sig.get('reason') if sig else None,'support':fnum(sig.get('support'),4) if sig else None,
      'is_new_signal':is_new,'previous_signal':psig.get('type') if psig else None,'wait':wait,
      'trend_holder_exit_next_open':bool(c.Close<c.SMA20),
      'bottom_full_tp50_next_open':bool(c.Close>=c.SMA20),
      'bottom_runner_exit_next_open':bool(c.Close<c.SMA20),
    }


def main():
    generated=datetime.now(KST)
    rows=[]; errors=[]
    for t,n in UNIVERSE.items():
        print(f'[signal] {n} {t}',flush=True)
        try: rows.append(analyze_one(t,n))
        except Exception as e:
            errors.append({'ticker':t,'name':n,'error':repr(e)})
            print('  ERROR',repr(e),file=sys.stderr,flush=True)
    # 안전 우선: ACTIVE 12 중 하나라도 실패하면 오래된 정상 신호 파일을 유지하도록 실행 실패.
    if errors:
        Path('data').mkdir(exist_ok=True)
        Path('data/last_engine_errors.json').write_text(json.dumps({'generated_at':generated.isoformat(),'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
        raise SystemExit(f'신호 계산 실패 {len(errors)}/{len(UNIVERSE)}개. 기존 latest_signals.json을 덮어쓰지 않습니다.')
    # ACTIVE 12 한국상장 ETF는 같은 거래 캘린더를 쓰므로 LIVE에서는 데이터 종가일 동기화를 확인한다.
    # 일부 소스만 한 거래일 이상 뒤처지면 오래된/부분 데이터를 신호로 쓰지 않고 실패시킨다.
    data_ends=[r['data_end'] for r in rows]
    market_data_end=max(set(data_ends), key=data_ends.count)
    stale_rows=[r for r in rows if r['data_end']!=market_data_end]
    if stale_rows:
        Path('data').mkdir(exist_ok=True)
        detail=[{'ticker':r['ticker'],'name':r['name'],'data_end':r['data_end'],'market_data_end':market_data_end} for r in stale_rows]
        Path('data/last_engine_errors.json').write_text(
            json.dumps({'generated_at':generated.isoformat(),'error':'DATA_END_MISMATCH','details':detail},ensure_ascii=False,indent=2),
            encoding='utf-8'
        )
        raise SystemExit(f'데이터 종가일 불일치 {len(stale_rows)}개. 기존 latest_signals.json을 유지합니다.')

    # 최신 완료주봉 날짜는 가장 빈도가 높은 날짜 사용.
    week_dates=[r['weekly_date'] for r in rows]
    signal_week=max(set(week_dates),key=week_dates.count)
    stale_week=[r for r in rows if r['weekly_date']!=signal_week]
    if stale_week:
        raise SystemExit(f'완료주봉 날짜 불일치 {len(stale_week)}개. 기존 latest_signals.json을 유지합니다.')
    # 포트폴리오 신규후보 정렬 (V5.4: TREND 우선, strength 내림차순)
    candidates=[r for r in rows if r['signal']]
    candidates.sort(key=lambda r:(1 if r['signal']=='TREND' else 0, r['signal_strength'] or 0),reverse=True)
    payload={
      'schema_version':3,
      'engine':'V5.4 LIVE SIGNAL ENGINE ACTIVE12 FINAL OOS',
      'strategy_id':'V54-ACTIVE12-BOTH-6S-FIXED5-KOFR-FINAL',
      'generated_at_kst':generated.isoformat(),
      'signal_week_end':signal_week,
      'market_data_end':market_data_end,
      'execution_rule':'완료주봉 다음 실제 거래일 시가. 시가를 놓치면 추격매수하지 않고 다음 완료주봉까지 대기.',
      'rules':{'active_etfs':12,'max_positions':6,'hard_stop_pct':5.0,'same_theme_max':1,'macd_mode':'loose','rsi_method':'sma','kofr_parking':True,'universe_policy':'duplicate_reduced'},
      'success_count':len(rows),'errors':[],
      'candidates_ranked':[{'rank':i+1,'ticker':r['ticker'],'name':r['name'],'signal':r['signal'],'is_new_signal':r['is_new_signal'],'strength':r['signal_strength']} for i,r in enumerate(candidates)],
      'items':rows,
    }
    out=Path('data'); hist=out/'history'; out.mkdir(exist_ok=True); hist.mkdir(exist_ok=True)
    txt=json.dumps(payload,ensure_ascii=False,indent=2)
    (out/'latest_signals.json').write_text(txt,encoding='utf-8')
    (hist/f'{signal_week}.json').write_text(txt,encoding='utf-8')
    print(f'OK {len(rows)}/12 | week={signal_week} | candidates={len(candidates)}')

if __name__=='__main__':
    main()
