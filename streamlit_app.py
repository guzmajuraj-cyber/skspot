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
        data.append({"Čas": dt, "Spotreba_kWh": round(spotreba * 0.25, 3)})
        
    df_demo = pd.DataFrame(data)
    df_demo.set_index("Čas", inplace=True)
    return df_demo

# --- HLAVNÉ ROZHRANIE APLIKÁCIE ---

st.markdown('<div class="main-title">⚡ SpotCheck Slovensko</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Zistite okamžite a nezáväzne, či by sa vám oplatil prechod na spotové ceny elektriny na základe vašich reálnych dát z inteligentného elektromeru.</div>', unsafe_allow_html=True)

# --- SIDEBAR (NASTAVENIA) ---
st.sidebar.header("⚙️ Nastavenia a Konfigurácia")

st.sidebar.subheader("💶 Porovnávacie parametre")
cena_fix_input = st.sidebar.slider(
    "Vaša súčasná fixovaná cena komodity (v centoch/kWh s DPH)",
    min_value=10.0, max_value=25.0, value=16.5, step=0.5
)
cena_fix_eur = cena_fix_input / 100.0

marza_dodavatela = st.sidebar.slider(
    "Odhadovaná marža spotového dodávateľa (EUR/MWh)",
    min_value=5, max_value=25, value=15, step=1
) / 1000.0

# --- HLAVNÝ OBSAH ---
tabs = st.tabs(["📊 Analýza a Porovnanie", "💡 Ako získať dáta z SSD?", "💰 Možnosti Úspory"])

with tabs[0]:
    col_left, col_right = st.columns([1, 2])
    
    with col_left:
        st.write("### 📂 Krok 1: Nahrajte dáta")
        uploaded_file = st.file_uploader(
            "Nahrajte export (CSV alebo XLSX) z portálu Stredoslovenskej distribučnej (SSD)", 
            type=["csv", "xlsx"]
        )
        use_demo = st.checkbox("Nemám pri sebe súbor, použiť **Demo ukážku** (1. - 15. Máj)")
        
    df_spotreba = None
    if uploaded_file is not None:
        df_spotreba = parsuj_ssd_subor(uploaded_file)
    elif use_demo:
        df_spotreba = vygeneruj_vzorove_data()
        
    if df_spotreba is not None:
        min_date = df_spotreba.index.min()
        max_date = df_spotreba.index.max()
        
        with st.spinner("⏳ Sťahujem a párujem 15-minútové spotové ceny priamo z OKTE..."):
            df_ceny = stiahni_spotove_ceny(min_date, max_date)
            
        if df_ceny is not None:
            df_final = df_spotreba.join(df_ceny, how='inner')
            
            if not df_final.empty:
                df_final['Cena_Spot_Koncova'] = df_final['cena_eur_kwh'] + marza_dodavatela
                df_final['Naklady_Spot_EUR'] = df_final['Spotreba_kWh'] * df_final['Cena_Spot_Koncova']
                df_final['Naklady_Fix_EUR'] = df_final['Spotreba_kWh'] * cena_fix_eur
                
                celkova_spotreba = df_final['Spotreba_kWh'].sum()
                naklady_spot_total = df_final['Naklady_Spot_EUR'].sum()
                naklady_fix_total = df_final['Naklady_Fix_EUR'].sum()
                
                uspora = naklady_fix_total - naklady_spot_total
                priemerna_cena_spot = naklady_spot_total / celkova_spotreba if celkova_spotreba > 0 else 0
                
                st.write("### 📈 Krok 2: Finálny verdikt")
                if uspora > 0:
                    st.success(f"🎉 Na spote by ste za toto obdobie **UŠETRILI {uspora:.2f} EUR** oproti vášmu fixu!")
                else:
                    st.warning(f"⚠️ Pri vašom aktuálnom profile by ste na spote **PREPLATILI {abs(uspora):.2f} EUR**. Oplatí sa zostať pri fixe.")
                    
                m_col1, m_col2, m_col3 = st.columns(3)
                with m_col1:
                    st.markdown(f'<div class="metric-card"><div class="metric-label">Celková Spotreba</div><div class="metric-value">{celkova_spotreba:.1f} kWh</div></div>', unsafe_allow_html=True)
                with m_col2:
                    st.markdown(f'<div class="metric-card"><div class="metric-label">Priemerná cena na Spote</div><div class="metric-value">{priemerna_cena_spot*100:.2f} ct/kWh</div></div>', unsafe_allow_html=True)
                with m_col3:
                    st.markdown(f'<div class="metric-card" style="border-left-color: #10B981;"><div class="metric-label">Vaša fixná cena</div><div class="metric-value">{cena_fix_input:.2f} ct/kWh</div></div>', unsafe_allow_html=True)
                
                st.write("### 📊 Priebeh spotreby a trhových cien")
                df_graf = df_final.copy()
                if len(df_graf) > 500:
                    # Ak je dát príliš veľa (napr. celý rok), zosumarizujeme ich na dni, aby graf netrhal
                    df_graf_resampled = pd.DataFrame({
                        'Denná Spotreba (kWh)': df_graf['Spotreba_kWh'].resample('d').sum(),
                        'Priemerná Denná Cena (EUR/MWh)': (df_graf['cena_eur_kwh'] * 1000).resample('d').mean()
                    })
                    st.line_chart(df_graf_resampled, height=350)
                else:
                    df_graf_visual = pd.DataFrame({
                        'Spotreba (kWh)': df_graf['Spotreba_kWh'],
                        'Spotová cena (ct/kWh)': df_graf['Cena_Spot_Koncova'] * 100
                    })
                    st.line_chart(df_graf_visual, height=350)
                
                st.write("### 📥 Stiahnuť detailný report")
                csv_buffer = io.StringIO()
                df_final[['Spotreba_kWh', 'Cena_Spot_Koncova', 'Naklady_Spot_EUR', 'Naklady_Fix_EUR']].to_csv(csv_buffer)
                st.download_button(
                    label="Stiahnuť prepočítané dáta (CSV)",
                    data=csv_buffer.getvalue(),
                    file_name="spotcheck_vysledky.csv",
                    mime="text/csv"
                )
            else:
                st.error("Chyba: Nepodarilo sa spárovať dáta o spotrebe.")

with tabs[1]:
    st.write("""
    ### 📑 Ako stiahnuť 15-minútové dáta zo Stredoslovenskej distribučnej?
    1. Prihláste sa do svojho zákazníckeho konta na portáli **Distančné odpočty SSD**.
    2. Prejdite do sekcie **Prehľad meraní / História spotreby**.
    3. Vyberte požadované obdobie (odporúča sa aspoň 1 celý mesiac).
    4. Zvoľte formát exportu **CSV** alebo **Excel (XLSX)** a uložte súbor.
    5. Nahrajte súbor na prvej karte tejto aplikácie.
    """)

with tabs[2]:
    st.write("""
    ### 💰 Ako vyťažiť zo spotového trhu maximum?
    * **Presun spotreby mimo špičky:** Najdrahšia elektrina býva ráno (8:00 - 10:00) a večer (18:00 - 21:00). Odložte umývačku alebo pranie na noc alebo poobedie.
    * **Využitie batérie a FVE:** Nabíjajte batérie zo sieťového napájania v noci za nízke ceny a spotrebúvajte ich počas drahej špičky.
    """)
