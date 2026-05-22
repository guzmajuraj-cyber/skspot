import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import io

# Nastavenie konfigurácie stránky
st.set_page_config(
    page_title="SpotCheck SK - Prepočet Spotovej Elektriny",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- INLINE CSS PRE KUSTOMIZÁCIU VZHĽADU ---
st.markdown("""
    <style>
    .main-title {
        font-size: 2.5rem;
        color: #1E3A8A;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    .sub-title {
        font-size: 1.1rem;
        color: #4B5563;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #F3F4F6;
        padding: 1.5rem;
        border-radius: 0.5rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        border-left: 5px solid #3B82F6;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: bold;
        color: #111827;
    }
    .metric-label {
        font-size: 0.9rem;
        color: #6B7280;
    }
    </style>
""", unsafe_allow_html=True)

# --- POMOCNÉ FUNKCIE PRE LOGIKU ---

@st.cache_data(ttl=3600)
def stiahni_spotove_ceny(den_od, den_do):
    """Stiahne reálne 15-minútové spotové ceny priamo z API OKTE (96 periód za deň)"""
    str_od = den_od.strftime("%Y-%m-%d")
    str_do = den_do.strftime("%Y-%m-%d")
    
    url = f"https://isot.okte.sk/api/v1/dam/results?deliveryDayFrom={str_od}&deliveryDayTo={str_do}"
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            st.error(f"❌ Chyba OKTE API (Kód {response.status_code})")
            return None
            
        data = response.json()
        ceny = []
        
        for zápis in data:
            den_str = zápis['deliveryDay']
            perioda = int(zápis['period'])   # Perióda 1 až 96
            cena_mwh = float(zápis['price'])  # Cena v EUR / MWh
            cena_kwh = cena_mwh / 1000.0      # Prepočet na EUR / kWh
            
            zaklad_dna = datetime.fromisoformat(den_str)
            # Perióda 1 je čas 00:00 - 00:15, preto pripočítavame (perioda - 1) * 15 minút
            realny_cas = zaklad_dna + timedelta(minutes=(perioda - 1) * 15)
            
            ceny.append({"cas": realny_cas, "cena_eur_kwh": cena_kwh})
            
        if not ceny:
            st.warning("⚠️ OKTE API nevrátilo pre toto obdobie žiadne dáta.")
            return None
            
        df_ceny = pd.DataFrame(ceny)
        df_ceny.set_index("cas", inplace=True)
        
        if df_ceny.index.tz is None:
            df_ceny.index = df_ceny.index.tz_localize('Europe/Bratislava', ambiguous='NaT', nonexistent='NaT')
        else:
            df_ceny.index = df_ceny.index.tz_convert('Europe/Bratislava')
            
        return df_ceny
        
    except Exception as e:
        st.error(f"Nepodarilo sa stiahnuť ceny z OKTE: {str(e)}")
        return None

def parsuj_ssd_subor(uploaded_file):
    """Bezpečne načíta nahraný CSV/XLSX súbor z SSD a ponechá ho v 15-minútovom rozlíšení"""
    try:
        if uploaded_file.name.endswith('.csv'):
            try:
                df = pd.read_csv(uploaded_file, sep=';', engine='python')
            except:
                df = pd.read_csv(uploaded_file, sep=None, engine='python')
        else:
            df = pd.read_excel(uploaded_file)
        
        cas_col = "Dátum a čas merania"
        spotreba_col = "1.5.0 - Činný odber (kW)"
        
        for col in df.columns:
            col_clean = str(col).lower().strip()
            if 'dátum a čas' in col_clean or 'datum a cas' in col_clean:
                cas_col = col
            if '1.5.0' in col_clean and 'odber' in col_clean:
                spotreba_col = col

        if cas_col not in df.columns or spotreba_col not in df.columns:
            st.error(f"❌ Súbor nemá očakávanú štruktúru SSD. Nenašli sa stĺpce pre čas alebo odber.")
            return None
            
        df = df[[cas_col, spotreba_col]].dropna()
        df[cas_col] = pd.to_datetime(df[cas_col], format="%d.%m.%Y %H:%M", errors='coerce')
        df = df.dropna()
        df.set_index(cas_col, inplace=True)
        
        if df.index.tz is None:
            df.index = df.index.tz_localize('Europe/Bratislava', ambiguous='NaT', nonexistent='NaT')
        else:
            df.index = df.index.tz_convert('Europe/Bratislava')
            
        # Prepočet: Výkon v kW prepočítame na energiu v kWh za 15 minút (kW * 0.25)
        df['Spotreba_kWh'] = df[spotreba_col] * 0.25
        
        # SSD označuje koniec intervalu (00:15), OKTE začiatok (00:00).
        # Posunieme index o 15 minút dozadu pre dokonalé spárovanie s OKTE.
        df_15min = df[['Spotreba_kWh']].copy()
        df_15min.index = df_15min.index - pd.Timedelta(minutes=15)
        
        return df_15min
        
    except Exception as e:
        st.error(f"Chyba pri čítaní súboru: {str(e)}")
        return None

def vygeneruj_vzorove_data():
    """Generuje ukážkové 15-minútové dáta pre demo režim"""
    casovy_rozsah = pd.date_range(start="2026-05-01", end="2026-05-15", freq='15min', tz='Europe/Bratislava')
    import random
    random.seed(42)
    
    data = []
    for dt in casovy_rozsah:
        hodina = dt.hour
        if 7 <= hodina <= 9 or 17 <= hodina <= 22:
            zaklad = 0.4
        else:
            zaklad = 0.1
        spotreba = zaklad + random.uniform(0.0, 0.3)
        # Generujeme rovno hodnotu, akoby prešla prepočtom na kWh
        data.append({"Čas": dt, "Spotreba_kWh": round(spotreba *
