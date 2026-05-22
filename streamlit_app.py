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
    """Bezpečne a univerzálne načíta akýkoľvek súbor (CSV, XLSX, XLS) z SSD distribučnej"""
    try:
        df = None
        
        # Pokus č. 1: Skúsime to prečítať ako CSV (mnohé .xls exporty sú len textové CSV premenované na Excel)
        encodings = ['utf-8', 'cp1250', 'iso-8859-2']
        separators = [',', ';']
        
        for enc in encodings:
            for sep in separators:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, sep=sep, encoding=enc, engine='python')
                    if not df.empty and len(df.columns) >= 2:
                        break
                except:
                    continue
            if df is not None and len(df.columns) >= 2:
                break
                
        # Pokus č. 2: Ak zlyhalo CSV čítanie, ide o reálny binárny Excel súbor (.xlsx alebo .xls)
        if df is None or len(df.columns) < 2:
            try:
                uploaded_file.seek(0)
                df = pd.read_excel(uploaded_file, skiprows=0)
            except:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_excel(uploaded_file, skiprows=0, engine='xlrd') # pre staré typy XLS
                except Exception as e:
                    st.error(f"❌ Nepodarilo sa rozkódovať Excel formát súboru. Skúste na portáli distribučnej vybrať čistý export do CSV. Detail: {str(e)}")
                    return None

        if df is None or df.empty:
            st.error("❌ Súbor sa podarilo otvoriť, ale je prázdny.")
            return None

        # Fix pre posunutú hlavičku (ak sú na začiatku súboru prázdne riadky alebo informácie o odbernom mieste)
        if "Dátum a čas merania" not in df.columns:
            for idx, row in df.iterrows():
                row_str = str(row.values).lower()
                if "dátum a čas" in row_str or "datum a cas" in row_str or "1.5.0" in row_str:
                    uploaded_file.seek(0)
                    # Opakovaný pokus s preskočením balastu na začiatku
                    try:
                        df = pd.read_csv(uploaded_file, sep=',', skiprows=idx+1, engine='python')
                    except:
                        try:
                            uploaded_file.seek(0)
                            df = pd.read_csv(uploaded_file, sep=';', skiprows=idx+1, engine='python')
                        except:
                            uploaded_file.seek(0)
                            df = pd.read_excel(uploaded_file, skiprows=idx+1)
                    break

        # Dynamická identifikácia stĺpcov podľa kľúčových slov
        cas_col = None
        spotreba_col = None
        dodavka_col = None   # Podpora pre FVE (Prebytky do siete)
        
        for col in df.columns:
            col_clean = str(col).lower().replace('\xa0', ' ').strip()
            if 'dátum a čas' in col_clean or 'datum a cas' in col_clean:
                cas_col = col
            if '1.5.0' in col_clean and 'odber' in col_clean:
                spotreba_col = col
            if '2.5.0' in col_clean and 'dodávka' in col_clean or 'dodavka' in col_clean:
                dodavka_col = col

        if not cas_col or not spotreba_col:
            st.error(f"❌ V súbore sa nenašli stĺpce pre 'Dátum a čas merania' alebo '1.5.0 - Činný odber'. Dostupné stĺpce v súbore sú: {list(df.columns)}")
            return None
            
        # Ponecháme iba tie stĺpce, ktoré naozaj ideme spracovať
        potrebne_stlpce = [cas_col, spotreba_col]
        if dodavka_col:
            potrebne_stlpce.append(dodavka_col)
            
        df = df[potrebne_stlpce].copy()
        
        # Flexibilná konverzia dátumov a časov
        df[cas_col] = pd.to_datetime(df[cas_col], errors='coerce')
        
        # Čistenie a číselná konverzia odberu (Spotreby)
        if df[spotreba_col].dtype == 'object':
            df[spotreba_col] = df[spotreba_col].astype(str).str.replace(',', '.').str.strip()
        df[spotreba_col] = pd.to_numeric(df[spotreba_col], errors='coerce').fillna(0.0)
        
        # Čistenie a číselná konverzia dodávky (Výroby z FVE), ak existuje
        if dodavka_col:
            if df[dodavka_col].dtype == 'object':
                df[dodavka_col] = df[dodavka_col].astype(str).str.replace(',', '.').str.strip()
            df[dodavka_col] = pd.to_numeric(df[dodavka_col], errors='coerce').fillna(0.0)
        else:
            df['Dodavka_FVE_kW'] = 0.0
            dodavka_col = 'Dodavka_FVE_kW'
            
        # Odstránenie riadkov s poškodeným dátumom
        df = df.dropna(subset=[cas_col])
        
        if df.empty:
            st.error("❌ Po očistení dát nezostali žiadne platné riadky. Skontrolujte formáty v súbore.")
            return None

        df.set_index(cas_col, inplace=True)
        
        # Nastavenie časového pásma pre Slovensko
        if df.index.tz is None:
            df.index = df.index.tz_localize('Europe/Bratislava', ambiguous='NaT', nonexistent='NaT')
        else:
            df.index = df.index.tz_convert('Europe/Bratislava')
            
        # Výpočet energie v kWh za 15-minútovú periódu (kW * 0.25 hodiny)
        df['Spotreba_kWh'] = df[spotreba_col] * 0.25
        df['Dodavka_kWh'] = df[dodavka_col] * 0.25
        
        # Posun indexu spätne o 15 minút kvôli párovaniu s OKTE (OKTE indexuje začiatok hodiny, SSD koniec periódy)
        df_15min = df[['Spotreba_kWh', 'Dodavka_kWh']].copy()
        df_15min.index = df_15min.index - pd.Timedelta(minutes=15)
        
        return df_15min
        
    except Exception as e:
        st.error(f"Kritická chyba pri spracovaní súboru: {str(e)}")
        return None


def vygeneruj_vzorove_data():
    """Generuje ukážkové dáta pre demo režim (predstiera dom bez FVE)"""
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
        data.append({"Čas": dt, "Spotreba_kWh": round(spotreba * 0.25, 3), "Dodavka_kWh": 0.0})
        
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
tabs = st.tabs([
    "📊 Analýza a Porovnanie", 
    "👀 Kontrola načítaných dát",
    "💡 Ako získať dáta z SSD?", 
    "💰 Možnosti Úspory"
])

with tabs[0]:
    col_left, col_right = st.columns([1, 2])
    
    with col_left:
        st.write("### 📂 Krok 1: Nahrajte dáta")
        uploaded_file = st.file_uploader(
            "Nahrajte export (CSV, XLSX alebo XLS) z portálu Stredoslovenskej distribučnej (SSD)", 
            type=["csv", "xlsx", "xls"]
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
        
        if pd.isna(min_date) or pd.isna(max_date):
            st.error("❌ Nepodarilo sa určiť časový rozsah dát. Skontrolujte formát dátumov.")
        else:
            with st.spinner("⏳ Sťahujem a párujem 15-minútové spotové ceny priamo z OKTE..."):
                df_ceny = stiahni_spotove_ceny(min_date, max_date)
                
            if df_ceny is not None:
                df_final = df_spotreba.join(df_ceny, how='inner')
                
                if not df_final.empty:
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
                        st.success(f"🎉 Na spote by ste za toto obdobie **UŠETRILI {uspora:.2f} EUR** oproti vášmu fixu za odobratú elektrinu!")
                    else:
                        st.warning(f"⚠️ Pri vašom aktuálnom profile by ste na spote za odber **PREPLATILI {abs(uspora):.2f} EUR**. Oplatí sa zostať pri fixe.")
                        
                    m_col1, m_col2, m_col3 = st.columns(3)
                    with m_col1:
                        st.markdown(f'<div class="metric-card"><div class="metric-label">Celkový Odber (Spotreba)</div><div class="metric-value">{celkova_spotreba:.1f} kWh</div></div>', unsafe_allow_html=True)
                    with m_col2:
                        st.markdown(f'<div class="metric-card"><div class="metric-label">Priemerná cena na Spote</div><div class="metric-value">{priemerna_cena_spot*100:.2f} ct/kWh</div></div>', unsafe_allow_html=True)
                    with m_col3:
                        if celkova_dodavka > 0:
                            st.markdown(f'<div class="metric-card" style="border-left-color: #10B981;"><div class="metric-label">Celková Dodávka (Prebytky FVE)</div><div class="metric-value" style="color: #10B981;">{celkova_dodavka:.1f} kWh</div></div>', unsafe_allow_html=True)
                        else:
                            st.markdown(f'<div class="metric-card" style="border-left-color: #6B7280;"><div class="metric-label">Vaša fixná cena odberu</div><div class="metric-value">{cena_fix_input:.2f} ct/kWh</div></div>', unsafe_allow_html=True)
                    
                    st.write("### 📊 Priebeh spotreby a trhových cien")
                    df_graf = df_final.copy()
                    if len(df_graf) > 500:
                        graf_dict = {
                            'Denný Odber (kWh)': df_graf['Spotreba_kWh'].resample('d').sum()
                        }
                        if celkova_dodavka > 0:
                            graf_dict['Denná Výroba/Dodávka (kWh)'] = df_graf['Dodavka_kWh'].resample('d').sum()
                        
                        df_graf_resampled = pd.DataFrame(graf_dict)
                        st.line_chart(df_graf_resampled, height=350)
                    else:
                        graf_dict_detail = {
                            'Odber (kWh)': df_graf['Spotreba_kWh']
                        }
                        if celkova_dodavka > 0:
                            graf_dict_detail['Dodávka do siete (kWh)'] = df_graf['Dodavka_kWh']
                            
                        df_graf_visual = pd.DataFrame(graf_dict_detail)
                        st.line_chart(df_graf_visual, height=350)
                    
                    st.write("### 📥 Stiahnuť detailný report")
                    csv_buffer = io.StringIO()
                    stlpce_na_export = ['Spotreba_kWh', 'Dodavka_kWh', 'Cena_Spot_Koncova', 'Naklady_Spot_EUR', 'Naklady_Fix_EUR']
                    df_final[stlpce_na_export].to_csv(csv_buffer)
                    st.download_button(
                        label="Stiahnuť prepočítané dáta (CSV)",
                        data=csv_buffer.getvalue(),
                        file_name="spotcheck_vysledky.csv",
                        mime="text/csv"
                    )
                else:
                    st.error("Chyba: Nepodarilo sa spárovať dáta o spotrebe s trhovými cenami OKTE.")

with tabs[1]:
    st.write("### 👀 Kontrola spracovaných dát")
    if df_spotreba is not None:
        st.info(f"📊 **Štatistika súboru:** V tabuľke sa nachádza celkovo **{len(df_spotreba)} riadkov** s 15-minútovými záznamami.")
        
        df_view = df_spotreba.copy()
        df_view.index = df_view.index.strftime('%Y-%m-%d %H:%M:%S')
        df_view.index.name = 'Dátum a Čas (upravený pre OKTE)'
        df_view.columns = ['Odber (kWh / 15min)', 'Dodávka FVE (kWh / 15min)']
        
        c1, c2 = st.columns(2)
        with c1:
            st.write("#### 🕒 Začiatok merania (Prvých 10 riadkov)")
            st.dataframe(df_view.head(10), use_container_width=True)
            
        with c2:
            st.write("#### 🚀 Koniec merania (Posledných 10 riadkov)")
            st.dataframe(df_view.tail(10), use_container_width=True)
            
        st.write("#### 📈 Rýchly prehľad hodnôt (Súhrnné sumy a priemery)")
        st.dataframe(df_spotreba.describe().T[['mean', 'min', 'max', 'sum']].rename(
            index={'Spotreba_kWh': 'Odber (Suma spotreby v kWh)', 'Dodavka_kWh': 'Dodávka (Suma prebytkov FVE v kWh)'},
            columns={'mean': 'Priemer na 15-min', 'min': 'Minimum', 'max': 'Maximum', 'sum': 'Suma spolu za celé obdobie'}
        ), use_container_width=True)
    else:
        st.warning("📂 Najprv nahrajte súbor, aby sa tu zobrazili dáta.")

with tabs[2]:
    st.write("""
    ### 📑 Ako stiahnuť 15-minútové dáta zo Stredoslovenskej distribučnej?
    1. Prihláste sa do svojho zákazníckeho konta na portáli **Distančné odpočty SSD**.
    2. Prejdite do sekcie **Prehľad meraní / História spotreby**.
    3. Vyberte požadované obdobie (odporúča sa aspoň 1 celý mesiac).
    4. Zvoľte formát exportu a uložte súbor.
    5. Nahrajte súbor na prvej karte tejto aplikácie.
    """)

with tabs[3]:
    st.write("""
    ### 💰 Ako vyťažiť zo spotového trhu maximum?
    * **Presun spotreby mimo špičky:** Najdrahšia elektrina býva ráno (8:00 - 10:00) a večer (18:00 - 21:00). Odložte umývačku alebo pranie na noc alebo poobedie.
    * **Využitie batérie a FVE:** Nabíjajte batérie zo sieťového napájania v noci za nízke ceny a spotrebúvajte ich počas drahej špičky.
    """)
