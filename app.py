"""
Streamlit app — Voorbladen invullen (Belisol PVC CERTIX)

Starten:
    cd ~/Claude/Projects/Automatisch\ invullen\ van\ voorbladen
    streamlit run app.py
"""

import io
import sys
from pathlib import Path

import fitz
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
import process_voorblad as pv

# ── Pagina-instellingen ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Voorbladen invullen",
    page_icon="🏠",
    layout="centered",
)

st.title("🏠 Voorbladen invullen")
st.caption("Belisol PVC CERTIX — vult voorbladen automatisch in op basis van de volgbladen")

st.divider()

# ── 1. PDF uploaden ───────────────────────────────────────────────────────────
uploaded = st.file_uploader(
    "Upload bestelbon PDF",
    type="pdf",
    help="Bestelbon met één of meerdere volgbladen",
)

if not uploaded:
    st.stop()

pdf_bytes = uploaded.getvalue()


# ── 2. PDF parsen (gecacht per bestand) ───────────────────────────────────────
@st.cache_data(show_spinner="Bestelbon lezen…")
def _parse(data: bytes):
    doc = fitz.open(stream=data, filetype="pdf")
    if len(doc) < 2:
        return None, [], []
    header = pv.extraheer_header(doc)
    specs  = [pv.parse_volgblad(doc[i]) for i in range(1, len(doc))]
    labels = []
    for i in range(1, len(doc)):
        regels = [r.strip() for r in doc[i].get_text("text").split("\n") if r.strip()]
        label  = next((r for r in regels if r.startswith("POS.")), f"Volgblad {i}")
        labels.append(label)
    return header, specs, labels


header, specs, pos_labels = _parse(pdf_bytes)

if not specs:
    st.error("Geen volgbladen gevonden in dit PDF. Zorg dat het bestand zowel voorbladen als volgbladen bevat.")
    st.stop()

st.success(f"✅ {len(specs)} element(en) gevonden")

# ── 3. Gedetecteerde info per element tonen ───────────────────────────────────
with st.expander("📋 Gedetecteerde info per element", expanded=False):
    for label, s in zip(pos_labels, specs):
        cols = st.columns([2, 2, 2, 2])
        cols[0].markdown(f"**{label}**")
        cols[1].markdown(f"Type: `{s.get('element_type') or '—'}`")
        cols[2].markdown(f"Glas: `{s.get('glas_str') or '—'}`")
        cols[3].markdown(f"Profiel: `{s.get('profiel_type') or '—'}`")

st.divider()

# ── 4. Merged spec opbouwen (consistentiechecks) ─────────────────────────────
merged: dict = specs[0].copy()

RAAM_KW = ["raam", "kozijn", "kiep", "schuif", "vast"]
merged["heeft_ramen"]  = any(any(kw in s.get("element_type", "").lower() for kw in RAAM_KW) for s in specs)
merged["heeft_deuren"] = any("deur" in s.get("element_type", "").lower() for s in specs)

# Raamgreep: meest voorkomende waarde
raamgrepen = [s["raamgreep"] for s in specs if s.get("raamgreep")]
if raamgrepen:
    merged["raamgreep"] = max(set(raamgrepen), key=raamgrepen.count)

# Raambeslag: meest voorkomende
rb_waarden = [s["raambeslag"] for s in specs if s.get("raambeslag") is not None]
merged["raambeslag"] = max(set(rb_waarden), key=rb_waarden.count) if rb_waarden else None

# Beslag type/kleur: meest voorkomende
b_types   = [s["beslag_type"]  for s in specs if s.get("beslag_type")]
b_kleuren = [s["beslag_kleur"] for s in specs if s.get("beslag_kleur")]
merged["beslag_type"]  = max(set(b_types),   key=b_types.count)   if b_types   else None
merged["beslag_kleur"] = max(set(b_kleuren), key=b_kleuren.count) if b_kleuren else None

# Deurgreep / deurscharnieren
dg = [s["deurgreep"]       for s in specs if s.get("deurgreep")]
ds = [s["deurscharnieren"] for s in specs if s.get("deurscharnieren")]
merged["deurgreep"]       = max(set(dg), key=dg.count) if dg else None
merged["deurscharnieren"] = max(set(ds), key=ds.count) if ds else None

# Met sleutel
opendraaiend = [s for s in specs if s.get("is_opendraaiend")]
afs_count    = sum(1 for s in opendraaiend if s.get("heeft_afsluitbare_kruk"))
merged["met_sleutel"] = afs_count == len(opendraaiend) and afs_count > 0

# ── 5. Formulier ─────────────────────────────────────────────────────────────
st.subheader("⚙️ Instellingen")

with st.form("instellingen"):

    # ── Beglazing ──
    st.markdown("**🪟 Beglazing**")
    glas_types    = [s["glas_type"]          for s in specs if s.get("glas_type")]
    glas_lagen_all = [tuple(s["glas_lagen"]) for s in specs if s.get("glas_lagen")]

    if glas_types and len(set(glas_types)) == 1 and len(set(glas_lagen_all)) == 1:
        st.info(f"Gevonden: **{specs[0].get('glas_str')}** ({glas_types[0]}) — consistent op alle volgbladen")
        glas_default = specs[0].get("glas_str", "")
    else:
        if glas_types:
            glas_overzicht = ", ".join(f"{l}: {s.get('glas_str','?')}" for l, s in zip(pos_labels, specs))
            st.warning(f"Verschillende beglazingen gevonden: {glas_overzicht}")
        glas_default = specs[0].get("glas_str", "") if glas_types else ""

    glas_input = st.text_input(
        "Glascode",
        value=glas_default,
        placeholder="bijv. 4/16/4 of 33.2/16/4/16/33.2",
        help="Even indices = glas (mm), oneven = spouw (mm)",
    )

    st.divider()

    # ── Profieltype ──
    st.markdown("**🔩 Profieltype**")
    profiel_detected = merged.get("profiel_type") or "aanslag"
    profiel = st.radio(
        "Profieltype",
        options=["aanslag", "stomp"],
        index=0 if profiel_detected == "aanslag" else 1,
        horizontal=True,
    )

    st.divider()

    # ── Raambeslag (alleen tonen bij inconsistentie) ──
    rb_uniek = list(set(rb_waarden))
    if len(rb_uniek) > 1:
        st.markdown("**🔒 Raambeslag**")
        st.warning(f"Inconsistent raambeslag gevonden: {rb_waarden}")
        raambeslag_keuze = st.radio("Raambeslag voor het voorblad", ["standaard", "skg"], horizontal=True)
    else:
        raambeslag_keuze = rb_uniek[0] if rb_uniek else None

    st.divider()

    # ── Maataanpassingen per element ──
    st.markdown("**📐 Maataanpassingen in tekeningen** *(leeg = geen wijziging)*")
    maat_invoer: dict[int, dict] = {}
    for idx, label in enumerate(pos_labels):
        st.markdown(f"*{label}*")
        col1, col2 = st.columns(2)
        with col1:
            b = st.text_input("Breedte", key=f"b_{idx}", placeholder="bijv. 980=1080")
        with col2:
            h = st.text_input("Hoogte",  key=f"h_{idx}", placeholder="bijv. 2290=2390")
        maat_invoer[idx] = {"breedte": b.strip(), "hoogte": h.strip()}

    st.divider()

    submitted = st.form_submit_button(
        "✅ Genereer ingevuld voorblad",
        type="primary",
        use_container_width=True,
    )


# ── 6. Verwerking ─────────────────────────────────────────────────────────────
if not submitted:
    st.stop()

merged["profiel_type"] = profiel
if raambeslag_keuze:
    merged["raambeslag"] = raambeslag_keuze

# Glas instellen
if glas_input.strip():
    merged["glas_type"], merged["glas_lagen"] = pv.parse_glas(glas_input.strip())
else:
    merged["glas_type"]  = None
    merged["glas_lagen"] = None

errors = []

with st.spinner("PDF wordt gegenereerd…"):

    # Vul het voorblad in
    try:
        result_doc = pv.vul_voorblad(header, merged)
    except Exception as e:
        st.error(f"Fout bij invullen voorblad: {e}")
        st.stop()

    # Maataanpassingen + Vak-B opschonen op volgbladen
    vb_doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for i in range(1, len(vb_doc)):
        idx = i - 1
        w   = maat_invoer.get(idx, {})

        def _pas_maat(invoer: str, zone: str):
            if not invoer or "=" not in invoer:
                return
            try:
                oud, nieuw = [int(x.strip()) for x in invoer.split("=", 1)]
                ok = pv.wijzig_maat_in_tekening(vb_doc[i], oud, nieuw, zone=zone)
                if not ok:
                    errors.append(f"{pos_labels[idx]} — maat {oud} niet gevonden in tekening")
            except ValueError:
                errors.append(f"{pos_labels[idx]} — ongeldig formaat '{invoer}', gebruik bijv. 980=1080")

        _pas_maat(w.get("breedte", ""), zone="bottom")
        _pas_maat(w.get("hoogte",  ""), zone="right")

        pv.process_volgblad(vb_doc[i])

    # Voeg volgbladen toe aan ingevuld voorblad
    result_doc.insert_pdf(vb_doc, from_page=1, to_page=len(vb_doc) - 1)

    # Sla op in geheugen
    buf = io.BytesIO()
    result_doc.save(buf)
    buf.seek(0)

# ── 7. Resultaat ──────────────────────────────────────────────────────────────
if errors:
    for e in errors:
        st.warning(f"⚠️ {e}")

st.success("✅ PDF klaar!")

output_naam = Path(uploaded.name).stem + "_ingevuld.pdf"
st.download_button(
    label="⬇️ Download ingevuld PDF",
    data=buf,
    file_name=output_naam,
    mime="application/pdf",
    use_container_width=True,
    type="primary",
)
