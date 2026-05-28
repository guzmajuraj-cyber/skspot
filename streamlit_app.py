import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import io
from decimal import Decimal, ROUND_HALF_UP

# Nastavenie konfigurácie stránky
st.set_page_config(
    page_title="SpotCheck SK - Prepočet Spotovej Elektriny",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Nastavenie globálnej presnosti pre knižnicu decimal
import decimal
decimal.getcontext().prec = 28

# --- INLINE CSS PRE KUSTOMIZÁCIU VZHĽADU ---
st.markdown("""
    <style>
    .main-title { font-size: 2.5rem; color: #1E3A8A; font-weight: 700; margin-bottom: 0.5rem; }
    .sub-title { font-size: 1.1rem; color: #4B5563; margin-bottom: 2rem; }
    .metric-card { background-color: #F3F4F6; padding: 1.2rem; border-radius: 0.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 5px solid #3B82F6; margin-bottom: 1rem; }
    .metric-value { font-size: 1.6rem; font-weight: bold; color: #111827; }
    .metric-label { font-size: 0.9rem; color: #6B7280; font-weight: 600; }
    .balance-card-positive { background-color: #ECFDF5; padding: 1.5rem; border-radius: 0.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 5px solid #10B981; }
    .balance-card-negative { background-color: #FEF2F2; padding: 1.5rem; border-radius: 0.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 5px solid #EF4444; }
    .period-info-card { background-color: #EFF6FF; padding: 0.75rem 1.2rem; border-radius: 0.5rem; border: 1px solid #BFDBFE; margin-top: 1.6rem; }
    </style>
""", unsafe_allow_html=True)

# --- POMOCNÉ FUNKCIE PRE LOGIKU ---

@st.cache_data(ttl=3600)
def stiahni_spotove_ceny(den_od, den_do):
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
            
        df_celkovy = pd.DataFrame(surove_data)
        pozadovane_stlpce = ['period', 'price', 'deliveryStart', 'deliveryEnd']
        existujuce_stlpce = [col for col in pozadovane_stlpce if col in df_celkovy.columns]
        df_surove = df_celkovy[existujuce_stlpce].copy()
        
        ceny_parsovane = []
        for zápis in surove_data:
            den_str = zápis['deliveryDay']
            perioda = int(zápis['period'])
            cena_mwh = Decimal(str(zápis['price']))
            cena_kwh = cena_mwh / Decimal('1000.0')
            
            zaklad_dna = datetime.fromisoformat(den_str)
            realny_cas = zaklad_dna + timedelta(minutes=(perioda - 1) * 15)
            ceny_parsovane.append({"cas": realny_cas, "cena_eur_kwh": float(cena_kwh)})
            
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
            
        df['Spotreba_kWh'] = df[spotreba_col].astype(float) * 0.25
        if dodavka_col:
            df['Dodavka_kWh'] = df[dodavka_col].astype(float) * 0.25
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
        dodavka = random.uniform(0.5, 1.5) if (10 <= hodina <= 16) else 0.0
        data.append({"Čas": dt, "Spotreba_kWh": round(spotreba * 0.25, 3), "Dodavka_kWh": round(dodavka * 0.25, 3)})
    df_demo = pd.DataFrame(data)
    df_demo.set_index("Čas", inplace=True)
    return df_demo

# --- HLAVNÉ ROZHRANIE ---
st.markdown('<div class="main-title">⚡ SpotCheck Slovensko</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Porovnanie fixných a reálnych spotových cien z OKTE.</div>', unsafe_allow_html=True)

st.sidebar.header("⚙️ Nastavenia")
cena_fix_input = st.sidebar.slider("Vaša fixná cena komodity (centy/kWh s DPH)", 10.0, 25.0, 16.5, 0.5)
cena_fix_eur = Decimal(str(cena_fix_input)) / Decimal('100.0')

marza_dodavatela_input = st.sidebar.slider("Marža spotového dodávateľa (EUR/MWh)", 5, 25, 15, 1)
marza_dodavatela = Decimal(str(marza_dodavatela_input)) / Decimal('1000.0')

tabs = st.tabs(["📊 Analýza a Porovnanie", "👀 Kontrola načítaných dát", "💡 Ako získať dáta?"])

df_surove_okte = None 
df_spotreba = None
vybrany_subor_nazov = "Demo ukážka"

with tabs[0]:
    st.write("### 📂 Krok 1: Nahrajte dáta")
    uploaded_files = st.file_uploader("Nahrajte exporty z SSD (Môžete vybrať viacero súborov naraz)", type=["csv", "xlsx", "xls"], accept_multiple_files=True)
    use_demo = st.checkbox("Použiť Demo ukážku", value=not uploaded_files)
    
    # NOVINKA: Rozdelenie riadku pre Selectbox a Informáciu o sledovanom období
    col_select, col_period = st.columns([1, 1])
    
    if uploaded_files:
        zoznam_suborov = {f.name: f for f in uploaded_files}
        with col_select:
            vybrany_subor_nazov = st.selectbox("🎯 Vyberte mesiac na analýzu:", list(zoznam_suborov.keys()))
        aktivny_subor = zoznam_suborov[vybrany_subor_nazov]
        df_spotreba = parsuj_ssd_subor(aktivny_subor)
    elif use_demo:
        df_spotreba = vygeneruj_vzorove_data()
        vybrany_subor_nazov = "Demo ukážka"
        with col_select:
            # Neaktívny selectbox pri demo dátach, aby držal vizuálnu štruktúru
            st.selectbox("🎯 Vyberte mesiac na analýzu:", ["Demo ukážka"], disabled=True)
            
    if df_spotreba is not None:
        min_date = df_spotreba.index.min()
        max_date = df_spotreba.index.max()
        
        # Sformátovanie dátumov pre zobrazenie
        str_od_zobrazenie = min_date.strftime("%d.%m.%Y %H:%M")
        str_do_zobrazenie = max_date.strftime("%d.%m.%Y %H:%M")
        
        # Vpísanie sledovaného obdobia vedľa výberového menu
        with col_period:
            st.markdown(f"""
            <div class="period-info-card">
                <span style="color: #1E40AF; font-weight: bold;">📅 Sledované obdobie:</span> 
                <span style="color: #1E1B4B;">{str_od_zobrazenie}</span> 
                <span style="color: #6B7280;">&nbsp;až&nbsp;</span> 
                <span style="color: #1E1B4B;">{str_do_zobrazenie}</span>
            </div>
            """, unsafe_allow_html=True)
        
        with st.spinner(f"⏳ Sťahujem spotové ceny z OKTE pre zvolené obdobie..."):
            df_surove_okte, df_ceny_parsovane = stiahni_spotove_ceny(min_date, max_date)
            
        if df_ceny_parsovane is not None:
            df_final = df_spotreba.join(df_ceny_parsovane, how='left')
            df_final['cena_eur_kwh'] = df_final['cena_eur_kwh'].ffill().bfill().fillna(0.0)
            
            naklady_spot_list = []
            naklady_fix_list = []
            vynosy_spot_list = []
            celkova_spotreba_dec = Decimal('0.0')
            celkova_dodavka_dec = Decimal('0.0')
            
            for index, row in df_final.iterrows():
                spotreba_15m = Decimal(str(row['Spotreba_kWh']))
                dodavka_15m = Decimal(str(row['Dodavka_kWh']))
                cena_trhova = Decimal(str(row['cena_eur_kwh']))
                
                n_spot = spotreba_15m * cena_trhova
                n_fix = spotreba_15m * cena_fix_eur
                v_spot = dodavka_15m * cena_trhova
                
                naklady_spot_list.append(float(n_spot))
                naklady_fix_list.append(float(n_fix))
                vynosy_spot_list.append(float(v_spot))
                
                celkova_spotreba_dec += spotreba_15m
                celkova_dodavka_dec += dodavka_15m
                
            df_final['Naklady_Spot_EUR'] = naklady_spot_list
            df_final['Naklady_Fix_EUR'] = naklady_fix_list
            df_final['Vynosy_Spot_EUR'] = vynosy_spot_list
            
            naklady_spot_total = sum(Decimal(str(x)) for x in naklady_spot_list)
            naklady_fix_total = sum(Decimal(str(x)) for x in naklady_fix_list)
            vynosy_spot_total = sum(Decimal(str(x)) for x in vynosy_spot_list)
            
            uspora = naklady_fix_total - naklady_spot_total
            bilancia_netto = vynosy_spot_total - naklady_spot_total
            
            p_celkova_spotreba = celkova_spotreba_dec.quantize(Decimal('1.00000000'), rounding=ROUND_HALF_UP)
            p_celkova_dodavka = celkova_dodavka_dec.quantize(Decimal('1.00000000'), rounding=ROUND_HALF_UP)
            p_naklady_spot_total = naklady_spot_total.quantize(Decimal('1.00000000'), rounding=ROUND_HALF_UP)
            p_vynosy_spot_total = vynosy_spot_total.quantize(Decimal('1.00000000'), rounding=ROUND_HALF_UP)
            p_uspora = uspora.quantize(Decimal('1.00000000'), rounding=ROUND_HALF_UP)
            p_bilancia_netto = bilancia_netto.quantize(Decimal('1.00000000'), rounding=ROUND_HALF_UP)
            
            st.write("### 📈 Krok 2: Finálny verdikt")
            
            if uspora > 0:
                st.success(f"🎉 Na čistom spote by ste v súbore `{vybrany_subor_nazov}` ušetrili **{p_uspora} EUR** voči fixnej tarife.")
            else:
                st.warning(f"⚠️ Na čistom spote by ste v súbore `{vybrany_subor_nazov}` preplatili **{abs(p_uspora)} EUR** voči fixnej tarife.")
            
            col_odber, col_dodavka = st.columns(2)
            
            with col_odber:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Celkový Odber</div>
                    <div class="metric-value">{p_celkova_spotreba} kWh</div>
                    <hr style='margin: 0.5rem 0; border: 0; border-top: 1px solid #D1D5DB;'>
                    <div class="metric-label">Celkový Odber (Vynásobený čistou cenou zo spotu)</div>
                    <div class="metric-value" style="color: #DC2626;">- {p_naklady_spot_total} €</div>
                </div>
                """, unsafe_allow_html=True)
                
            with col_dodavka:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Celková Dodávka</div>
                    <div class="metric-value">{p_celkova_dodavka} kWh</div>
                    <hr style='margin: 0.5rem 0; border: 0; border-top: 1px solid #D1D5DB;'>
                    <div class="metric-label">Celková Dodávka FVE (Vynásobená čistou cenou zo spotu)</div>
                    <div class="metric-value" style="color: #16A34A;">+ {p_vynosy_spot_total} €</div>
                </div>
                """, unsafe_allow_html=True)
            
            st.write("#### Čistá finančná bilancia")
            if bilancia_netto >= 0:
                st.markdown(f"""
                <div class="balance-card-positive">
                    <div class="metric-label" style="color: #065F46;">Výsledná bilancia (Výnosy - Náklady)</div>
                    <div class="metric-value" style="color: #047857;">+ {p_bilancia_netto} €</div>
                    <div style="margin-top: 0.5rem; font-weight: bold; color: #065F46;">💡 V danom období ste v zisku z predaja elektriny.</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="balance-card-negative">
                    <div class="metric-label" style="color: #991B1B;">Výsledná bilancia (Výnosy - Náklady)</div>
                    <div class="metric-value" style="color: #B91C1C;">{p_bilancia_netto} €</div>
                    <div style="margin-top: 0.5rem; font-weight: bold; color: #991B1B;">⚠️ V danom období ste dokúpili elektrinu.</div>
                </div>
                """, unsafe_allow_html=True)
            
            st.write("### 💶 Krok 3: Finančná bilancia (Prehľadová tabuľka)")
            p_cisty_rozdiel_kwh = (celkova_dodavka_dec - celkova_spotreba_dec).quantize(Decimal('1.00000000'), rounding=ROUND_HALF_UP)
            
            t3_data = {
                "Analytická položka": [
                    "Celkový Odber (Vynásobený čistou cenou zo spotu)", 
                    "Celková Dodávka FVE (Vynásobená čistou cenou zo spotu)", 
                    "Čistá finančná bilancia (Výnosy - Náklady)"
                ],
                "Množstvo [kWh]": [
                    f"{p_celkova_spotreba} kWh", 
                    f"{p_celkova_dodavka} kWh", 
                    f"{p_cisty_rozdiel_kwh} kWh"
                ],
                "Finančný výsledok [€]": [
                    f"- {p_naklady_spot_total} €", 
                    f"+ {p_vynosy_spot_total} €", 
                    f"{p_bilancia_netto} €"
                ]
            }
            st.table(pd.DataFrame(t3_data))

            st.write("### 🛠️ Porovnanie s Excelom (Audit)")
            df_audit = df_final.copy()
            df_audit.index = df_audit.index.strftime('%Y-%m-%d %H:%M:%S')
            
            csv_buffer = io.StringIO()
            df_audit.to_csv(csv_buffer, sep=';')
            st.download_button(
                label=f"📥 Stiahnuť 15-minútový report pre: {vybrany_subor_nazov} (.csv)",
                data=csv_buffer.getvalue(),
                file_name=f"spotcheck_{vybrany_subor_nazov}.csv",
                mime="text/csv"
            )
            
            st.write("### 📊 Priebeh spotreby a trhových cien")
            df_graf = df_final.copy()
            
            st.write("#### 🔌 Vaša spotreba a dodávka do siete (kWh)")
            graf_dict = {'Odber (kWh)': df_graf['Spotreba_kWh']}
            if float(p_celkova_dodavka) > 0:
                graf_dict['Dodávka (kWh)'] = df_graf['Dodavka_kWh']
            st.line_chart(pd.DataFrame(graf_dict), height=250)
            
            st.write("#### 💰 Finálny finančný priebeh (EUR za 15-min)")
            fin_graf_dict = {'Náklady na odber (€)': df_graf['Naklady_Spot_EUR'] * -1}
            if float(p_celkova_dodavka) > 0:
                fin_graf_dict['Výnosy z dodávky (€)'] = df_graf['Vynosy_Spot_EUR']
            st.line_chart(pd.DataFrame(fin_graf_dict), height=250, color=["#FF4B4B", "#29B560"])
            
            st.write("#### 💶 Vývoj ceny na spotovom trhu OKTE (centy/kWh s DPH)")
            df_graf['Spotová cena (ct/kWh)'] = df_graf['cena_eur_kwh'] * 100
            st.line_chart(df_graf[['Spotová cena (ct/kWh)']], height=200, color="#FF9F43")

with tabs[1]:
    st.write("### 👀 Kontrola načítaných dát")
    if df_spotreba is not None:
        df_view = df_spotreba.copy()
        df_view.index = df_view.index.strftime('%Y-%m-%d %H:%M:%S')
        df_view.index.name = 'Dátum a Čas (upravený pre OKTE)'
        df_view.columns = ['Odber (kWh / 15min)', 'Dodávka FVE (kWh / 15min)']
        
        st.write(f"#### 📋 Dáta z aktívneho súboru: `{vybrany_subor_nazov}`")
        st.dataframe(df_view, use_container_width=True)
        
        st.write("#### 🔍 Surové dáta z API OKTE pre toto obdobie:")
        if df_surove_okte is not None:
            st.dataframe(df_surove_okte, use_container_width=True, hide_index=True)
        else:
            st.error("❌ Žiadne surové dáta z OKTE neboli stiahnuté.")
    else:
        st.warning("📂 Najprv nahrajte aspoň jeden súbor.")

with tabs[2]:
    st.write("### 💡 Ako získať dáta?")
    st.write("Postup stiahnutia dát z portálu SSD (Stredoslovenská distribučná)...")
