import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import io

# Nastavenie konfigurácie stránky
st.set_page_config(
    page_title="OKTE Spot Data Viewer",
    page_icon="⚡",
    layout="wide"
)

st.markdown('<h2 style="color: #1E3A8A;">⚡ OKTE Spot Data Viewer</h2>', unsafe_allow_html=True)
st.markdown('<p style="color: #4B5563;">Vizualizácia čistých trhových cien priamo z API OKTE (Denný trh / DAM).</p>', unsafe_allow_html=True)

# --- POMOCNÁ FUNKCIA PRE API OKTE ---
@st.cache_data(ttl=3600)
def stiahni_surove_okte_data(den_od, den_do):
    """Stiahne dáta z API OKTE a vráti iba vybrané stĺpce: deliveryDay, period, price"""
    str_od = den_od.strftime("%Y-%m-%d")
    str_do = den_do.strftime("%Y-%m-%d")
    
    url = f"https://isot.okte.sk/api/v1/dam/results?deliveryDayFrom={str_od}&deliveryDayTo={str_do}"
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            st.error(f"❌ Chyba OKTE API (Kód {response.status_code})")
            return None
            
        surove_json = response.json()
        if not surove_json:
            st.warning("⚠️ API nevrátilo pre toto obdobie žiadne dáta.")
            return None
            
        # Vytvorenie DataFrame a filtrácia IBA na tebou požadované stĺpce
        df = pd.DataFrame(surove_json)
        
        # Ošetrenie, ak by náhodou API zmenilo názvy (garancia stĺpcov)
        dostupne_stlpce = df.columns
        filtrovane_stlpce = []
        
        for col in ['deliveryDay', 'period', 'price']:
            if col in dostupne_stlpce:
                filtrovane_stlpce.append(col)
                
        df_vysledny = df[filtrovane_stlpce].copy()
        return df_vysledny
        
    except Exception as e:
        st.error(f"Nepodarilo sa spojiť s API OKTE: {str(e)}")
        return None

# --- PARSER PRE TVOJ SUBOR (Zjednodušený) ---
def zisti_rozsah_datumu(uploaded_file):
    """Rýchlo prečíta nahraný súbor, aby sme vedeli, na aké dni stiahnuť OKTE ceny"""
    try:
        df = None
        for enc in ['utf-8', 'cp1250', 'iso-8859-2']:
            for sep in [',', ';']:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, sep=sep, encoding=enc, engine='python')
                    if df is not None and not df.empty: break
                except: continue
            if df is not None and not df.empty: break
            
        if df is None or df.empty:
            try:
                uploaded_file.seek(0)
                df = pd.read_excel(uploaded_file)
            except:
                return None, None

        # Nájdeme stĺpec s dátumom
        for col in df.columns:
            col_clean = str(col).lower().strip()
            if 'dátum a čas' in col_clean or 'datum a cas' in col_clean:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                df = df.dropna(subset=[col])
                return df[col].min(), df[col].max()
        return None, None
    except:
        return None, None

# --- ROZHRANIE A ZÁLOŽKY ---
tabs = st.tabs(["📈 Graf trhovej ceny (EUR/MWh)", "📋 Surové dáta (96 periód)"])

# Nahranie súboru slúži už len na to, aby aplikácia vedela, pre ktoré dni hľadáte ceny
uploaded_file = st.sidebar.file_uploader("Nahrajte SSD súbor pre zistenie dátumov", type=["csv", "xlsx", "xls"])
use_demo = st.sidebar.checkbox("Použiť demo rozsah (1. - 15. Máj 2026)", value=True if uploaded_file is None else False)

min_date, max_date = None, None

if uploaded_file is not None:
    min_date, max_date = zisti_rozsah_datumu(uploaded_file)
elif use_demo:
    min_date = datetime.strptime("2026-05-01", "%Y-%m-%d")
    max_date = datetime.strptime("2026-05-15", "%Y-%m-%d")

if min_date and max_date:
    st.sidebar.info(f"📅 Analyzované obdobie od: {min_date.strftime('%Y-%m-%d')} do: {max_date.strftime('%Y-%m-%d')}")
    
    with st.spinner("⏳ Ťahám dáta priamo z OKTE..."):
        df_okte = stiahni_surove_okte_data(min_date, max_date)
        
    if df_okte is not None:
        
        with tabs[0]:
            st.write("### 📊 Vývoj burzovej ceny na dennom trhu OKTE")
            
            # Pre účely čistého grafu vytvoríme dočasný časový index, aby line_chart fungoval správne časovo
            df_graf = df_okte.copy()
            df_graf['cas_index'] = pd.to_datetime(df_graf['deliveryDay']) + df_graf['period'].apply(lambda x: timedelta(minutes=(x-1)*15))
            df_graf.set_index('cas_index', inplace=True)
            
            # Premenujeme stĺpec v grafe, aby svietila správna jednotka
            df_graf_visual = pd.DataFrame({'Cena na OKTE (EUR/MWh)': df_graf['price']})
            st.line_chart(df_graf_visual, height=400, color="#FF9F43")
            
        with tabs[1]:
            st.write("### 🔍 Výpis požadovaných stĺpcov z OKTE API")
            st.info(f"Celkovo zobrazených **{len(df_okte)} riadkov** (96 periód za každý deň v rozsahu).")
            
            # Zobrazenie presne tých stĺpcov, ktoré ťa zaujímajú, bez indexov a úprav cien
            st.dataframe(df_okte[['deliveryDay', 'period', 'price']], use_container_width=True)
            
            # Možnosť stiahnuť čisté dáta
            csv_buffer = io.StringIO()
            df_okte[['deliveryDay', 'period', 'price']].to_csv(csv_buffer, index=False)
            st.download_button(
                label="📥 Stiahnuť tieto OKTE dáta (CSV)",
                data=csv_buffer.getvalue(),
                file_name="okte_surove_data.csv",
                mime="text/csv"
            )
else:
    st.warning("📂 Nahrajte súbor z distribučky alebo nechajte začiarknuté Demo, aby aplikácia vedela stiahnuť ceny.")
