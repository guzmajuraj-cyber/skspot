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
    .main-title { font-size: 2.5rem; color: #1E3A8A; font-weight: 700; margin-bottom: 0.5rem; }
    .sub-title { font-size: 1.1rem; color: #4B5563; margin-bottom: 2rem; }
    .metric-card { background-color: #F3F4F6; padding: 1.5rem; border-radius: 0.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 5px solid #3B82F6; }
    .metric-value { font-size: 1.8rem; font-weight: bold; color: #111827; }
    .metric-label { font-size: 0.9rem; color: #6B7280; }
    </style>
""", unsafe_allow_html=True)

# --- POMOCNÉ FUNKCIE PRE LOGIKU ---

@st.cache_data(ttl=3600)
def stiahni_spotove_ceny(den_od, den_do):
    """Stiahne dáta z API OKTE a vráti surovú tabuľku AJ tabuľku pripravenú na párovanie"""
    str_od = den_od.strftime("%Y-%m-%d")
    str_do = den_do.strftime("%Y-%m-%d")
    
    url = f"https://isot.okte.sk/api/v1/dam/results?deliveryDayFrom={str_od}&deliveryDayTo={str_do}"
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            st.error(f"❌ Chyba OKTE API (Kód {response.status_code})")
            return None, None
            
        surove_data = response.json()
        if not surove_data:
            st.warning("⚠️ OKTE API nevrátilo pre toto obdobie žiadne dáta.")
            return None, None
            
        # 1. VYTVORENIE SUROVEJ TABUĽKY (PRESNE AKO PRIŠLA Z API)
        df_surove = pd.DataFrame(surove_data) # Obsahuje stĺpce: deliveryDay, period, price
        
        # 2. PRÍPRAVA PARSOVANEJ TABUĽKY PRE GRAFY A PREPOČTY
        ceny_parsovane = []
        for zápis in surove_data:
            den_str = zápis['deliveryDay']
            perioda = int(zápis['period'])
            cena_mwh = float(zápis['price'])
            cena_kwh = cena_mwh / 1000.0
            
            zaklad_dna = datetime.fromisoformat(den_str)
            realny_cas = zaklad_dna + timedelta(minutes=(perioda - 1) * 15)
            ceny_parsovane.append({"cas": realny_cas, "cena_eur_kwh": cena_kwh})
            
        df_parsovane = pd.DataFrame(ceny_parsovane)
        df_parsovane.set_index("cas", inplace=True)
        
        if df_parsovane.index.tz is None:
            df_parsovane.index = df_parsovane.index.tz_localize('Europe/Bratislava', ambiguous='NaT', nonexistent='NaT')
        else:
            df_parsovane.index = df_parsovane.index.tz_convert('Europe/Bratislava')
            
        return df_surove, df_parsovane
        
    except Exception as e:
        st.error(f"Nepodarilo sa stiahnuť ceny z OKTE: {str(e)}")
        return None, None


def parsuj_ssd_subor(uploaded_file):
    """Robustne načíta a spracuje SSD súbor bez zbytočných textových konverzií"""
    try:
        df = None
        encodings = ['utf-8', 'cp1250', 'iso-8859-2']
        separators = [',', ';']
        
        for enc in encodings:
            for sep in separators:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, sep=sep, encoding=enc, engine='python')
                    if df is not None and not df.empty and len(df.columns) >= 2:
                        break
                except:
                    continue
            if df is not None and len(df.columns) >= 2:
                break
                
        if df is None or len(df.columns) < 2:
            try:
                uploaded_file.seek(0)
                df = pd.read_excel(uploaded_file, skiprows=0)
            except:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_excel(uploaded_file, skiprows=0, engine='xlrd')
                except Exception as e:
                    st.error(f"❌ Nepodarilo sa otvoriť súbor: {str(e)}")
                    return None

        if df is None or df.empty:
            st.error("❌ Súbor je prázdny.")
            return None

        cas_col = None
        spotreba_col = None
        dodavka_col = None
        
        for col in df.columns:
            col_clean = str(col).lower().replace('\xa0', ' ').strip()
            if 'dátum a čas' in col_clean or 'datum a cas' in col_clean:
                cas_col = col
            if '1.5.0' in col_clean and 'odber' in col_clean and 'kvalita' not in col_clean:
                spotreba_col = col
            if '2.5.0' in col_clean and ('dodávka' in col_clean or 'dodavka' in col_clean) and 'kvalita' not in col_clean:
                dodavka_col = col

        if not cas_col or not spotreba_col:
            st.error(f"❌ Nenašli sa stĺpce pre čas alebo odber. Dostupné stĺpce: {list(df.columns)}")
            return None
            
        potrebne_stlpce = [cas_col, spotreba_col]
        if dodavka_col:
            potrebne_stlpce.append(dodavka_col)
            
        df = df[potrebne_stlpce].copy()
        df[cas_col] = pd.to_datetime(df[cas_col], errors='coerce')
        df = df.dropna(subset=[cas_col])
        df.set_index(cas_col, inplace=True)
        
        if df.index.tz is None:
            df.index = df.index.tz_localize('Europe/Bratislava', ambiguous='NaT', nonexistent='NaT')
        else:
            df.index = df.index.tz_convert('Europe/Bratislava')
            
        df['Spotreba_kWh'] = df[spotreba_col] * 0.25
        if dodavka_col:
            df['Dodavka_kWh'] = df[dodavka_col] * 0.25
        else:
            df['Dodavka_kWh'] = 0.0
            
        df_15min = df[['Spotreba_kWh', 'Dodavka_kWh']].copy()
        df_15min.index = df_15min.index - pd.Timedelta(minutes=15)
        
        return df_15min
        
    except Exception as e:
        st.error(f"Kritická chyba pri spracovaní súboru: {str(e)}")
        return None


def vygeneruj_vzorove_data():
    casovy_rozsah = pd.date_range(start="2026-05-01", end="2026-05-15", freq='15min', tz='Europe/Bratislava')
    import random
    random.seed(42)
    data = []
    for dt in casovy_rozsah:
        hodina = dt.hour
        zaklad = 0.4 if (7 <= hodina <= 9 or 17 <= hodina <= 22) else 0.1
        spotreba = zaklad + random.uniform(0.0, 0.3)
        data.append({"Čas": dt, "Spotreba_kWh": round(spotreba * 0.25, 3), "Dodavka_kWh": 0.0})
    df_demo = pd.DataFrame(data)
    df_demo.set_index("Čas", inplace=True)
    return df_demo

# --- HLAVNÉ ROZHRANIE ---
st.markdown('<div class="main-title">⚡ SpotCheck Slovensko</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Porovnanie fixných a reálnych spotových cien z OKTE.</div>', unsafe_allow_html=True)

st.sidebar.header("⚙️ Nastavenia")
cena_fix_input = st.sidebar.slider("Vaša fixná cena komodity (centy/kWh s DPH)", 10.0, 25.0, 16.5, 0.5)
cena_fix_eur = cena_fix_input / 100.0

marza_dodavatela = st.sidebar.slider("Marža spotového dodávateľa (EUR/MWh)", 5, 25, 15, 1) / 1000.0

tabs = st.tabs(["📊 Analýza a Porovnanie", "👀 Kontrola načítaných dát", "💡 Ako získať dáta?"])

# Globálne premenné na prenos dát do záložky 1
df_surove_okte = None 

with tabs[0]:
    col_left, col_right = st.columns([1, 2])
    with col_left:
        st.write("### 📂 Krok 1: Nahrajte dáta")
        uploaded_file = st.file_uploader("Nahrajte export z SSD (CSV, XLSX, XLS)", type=["csv", "xlsx", "xls"])
        use_demo = st.checkbox("Použiť Demo ukážku")
        
    df_spotreba = None
    if uploaded_file is not None:
        df_spotreba = parsuj_ssd_subor(uploaded_file)
    elif use_demo:
        df_spotreba = vygeneruj_vzorove_data()
        
    if df_spotreba is not None:
        min_date = df_spotreba.index.min()
        max_date = df_spotreba.index.max()
        
        with st.spinner("⏳ Sťahujem spotové ceny z OKTE..."):
            df_surove_okte, df_ceny_parsovane = stiahni_spotove_ceny(min_date, max_date)
            
        if df_ceny_parsovane is not None:
            df_final = df_spotreba.join(df_ceny_parsovane, how='left')
            df_final['cena_eur_kwh'] = df_final['cena_eur_kwh'].ffill().bfill().fillna(0.0)
            
            df_final['Cena_Spot_Koncova'] = df_final['cena_eur_kwh'] + marza_dodavatela
            df_final['Naklady_Spot_EUR'] = df_final['Spotreba_kWh'] * df_final['Cena_Spot_Koncova']
            df_final['Naklady_Fix_EUR'] = df_final['Spotreba_kWh'] * cena_fix_eur
            
            celkova_spotreba = df_final['Spotreba_kWh'].sum()
            celkova_dodavka = df_final['Dodavka_kWh'].sum()
            naklady_spot_total = df_final['Naklady_Spot_EUR'].sum()
            naklady_fix_total = df_final['Naklady_Fix_EUR'].sum()
            uspora = naklady_fix_total - naklady_spot_total
            priemerna_cena_spot = naklady_spot_total / celkova_spotreba if celkova_spotreba > 0 else 0
            
            st.write("### 📈 Krok 2: Finálny verdikt")
            if uspora > 0:
                st.success(f"🎉 Na spote by ste ušetrili **{uspora:.2f} EUR**!")
            else:
                st.warning(f"⚠️ Na spote by ste preplatili **{abs(uspora):.2f} EUR**.")
                
            m_col1, m_col2, m_col3 = st.columns(3)
            with m_col1: st.markdown(f'<div class="metric-card"><div class="metric-label">Celkový Odber</div><div class="metric-value">{celkova_spotreba:.1f} kWh</div></div>', unsafe_allow_html=True)
            with m_col2: st.markdown(f'<div class="metric-card"><div class="metric-label">Priemerná cena Spot</div><div class="metric-value">{priemerna_cena_spot*100:.2f} ct/kWh</div></div>', unsafe_allow_html=True)
            with m_col3: st.markdown(f'<div class="metric-card"><div class="metric-label">Celková Dodávka</div><div class="metric-value">{celkova_dodavka:.1f} kWh</div></div>', unsafe_allow_html=True)
            
            st.write("### 📊 Priebeh spotreby a trhových cien")
            df_graf = df_final.copy()
            
            st.write("#### 🔌 Vaša spotreba a dodávka do siete (kWh)")
            graf_dict = {'Odber (kWh)': df_graf['Spotreba_kWh']}
            if celkova_dodavka > 0:
                graf_dict['Dodávka (kWh)'] = df_graf['Dodavka_kWh']
            st.line_chart(pd.DataFrame(graf_dict), height=250)
            
            st.write("#### 💶 Vývoj ceny na spotovom trhu OKTE (centy/kWh s DPH)")
            df_graf['Spotová cena (ct/kWh)'] = df_graf['Cena_Spot_Koncova'] * 100
            st.line_chart(df_graf[['Spotová cena (ct/kWh)']], height=200, color="#FF9F43")

with tabs[1]:
    st.write("### 👀 Kontrola spracovaných dát")
    if df_spotreba is not None:
        # Výpis tvojej distribučnej tabuľky
        df_view = df_spotreba.copy()
        df_view.index = df_view.index.strftime('%Y-%m-%d %H:%M:%S')
        df_view.index.name = 'Dátum a Čas (upravený pre OKTE)'
        df_view.columns = ['Odber (kWh / 15min)', 'Dodávka FVE (kWh / 15min)']
        
        st.write("#### 📋 Kompletné namerané dáta z vášho súboru (Odber a Dodávka):")
        st.dataframe(df_view, use_container_width=True)
        
        # NOVÝ SUROVÝ VÝPIS Z OKTE (BEZ ÚPRAV)
        st.write("#### 🔍 Surové dáta z API OKTE (Presne ako prišli zo serveru):")
        if df_surove_okte is not None:
            # Zobrazí presne stĺpce deliveryDay, period, price bez modifikácie indexu či hodnôt
            st.dataframe(df_surove_okte, use_container_width=True)
        else:
            st.error("❌ Žiadne surové dáta z OKTE neboli stiahnuté.")
            
        st.write("#### 📈 Rýchly prehľad hodnôt (Súhrnné sumy a priemery)")
        st.dataframe(df_spotreba.describe().T[['mean', 'min', 'max', 'sum']].rename(
            index={'Spotreba_kWh': 'Odber (Suma spotreby v kWh)', 'Dodavka_kWh': 'Dodávka (Suma prebytkov FVE v kWh)'},
            columns={'mean': 'Priemer na 15-min', 'min': 'Minimum', 'max': 'Maximum', 'sum': 'Suma spolu za celé obdobie'}
        ), use_container_width=True)
    else:
        st.warning("📂 Najprv nahrajte súbor.")

with tabs[2]:
    st.write("Postup stiahnutia dát z portálu SSD...")
