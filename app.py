"""
Streamlit app — Voorbladen invullen (Belisol PVC CERTIX)

Upload de volgbladen-PDF. De app genereert automatisch de voorbladen.

Starten:
    streamlit run app.py
"""

import base64
import io
import sys
from pathlib import Path

import fitz
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent))
import process_voorblad as pv

# ── Pagina-instellingen ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Voorbladen invullen",
    page_icon="🏠",
    layout="wide",
)

# ── Session state ──────────────────────────────────────────────────────────────
if 'preview_page'     not in st.session_state: st.session_state.preview_page     = 0
if 'last_upload_name' not in st.session_state: st.session_state.last_upload_name = None
if 'afw_acties'       not in st.session_state: st.session_state.afw_acties       = {}
# afw_acties: {(elem_pagina_idx, afw_label): ('genegeerd'|'aangepast'|'gewijzigd'|'wijzigen_actief', tekst)}


# ── Gecachte functies (module-niveau) ─────────────────────────────────────────
@st.cache_data(show_spinner="Volgbladen lezen…")
def _parse(data: bytes):
    doc       = fitz.open(stream=data, filetype="pdf")
    header    = pv.extraheer_header_uit_volgblad(doc[0])
    specs     = [pv.parse_volgblad(doc[i]) for i in range(len(doc))]
    elementen = pv.verdeel_in_elementen(specs)
    groepen   = pv.groepeer_volgbladen(specs)
    return header, specs, elementen, groepen


@st.cache_data(show_spinner="Voorbladen genereren…")
def _genereer(pdf_bytes: bytes, pm_frozen: tuple, afw_acties_frozen: tuple = ()) -> bytes:
    """Genereert de ingevulde PDF. Gecached op basis van alle inputs.

    pm_frozen: tuple van (elem_idx, breedte_str, hoogte_str)
      - breedte_str/hoogte_str zijn de door de gebruiker ingevoerde PM-maaten
      - Zijn deze afwijkend van offer_breedte/offer_hoogte, dan wordt ook
        de maatvoering in de tekening bijgewerkt.

    afw_acties_frozen: tuple van (elem_idx, afw_label, status, custom_tekst)
      status: 'genegeerd' | 'aangepast' | 'gewijzigd'
    """
    header, specs, elementen, groepen = _parse(pdf_bytes)

    # frozen inputs → dict reconstrueren
    pm_invoer = {k: {'breedte': b, 'hoogte': h} for k, b, h in pm_frozen}

    # Afwijking-acties: {(elem_idx, afw_label): (status, custom_tekst)}
    afw_acties = {(ei, lbl): (status, txt) for ei, lbl, status, txt in afw_acties_frozen}

    vb_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    result = fitz.open()

    for groep_naam, groep_idx in groepen:
        groep_idx_set   = set(groep_idx)
        groep_specs     = [specs[i] for i in groep_idx]
        groep_spec      = pv.bepaal_groep_spec(groep_specs)
        groep_elementen = [el for el in elementen if el['paginas'][0] in groep_idx_set]

        voorblad_doc = pv.vul_voorblad(header, groep_spec)
        result.insert_pdf(voorblad_doc)

        for el in groep_elementen:
            stuks       = el['spec'].get('stuks', 1)
            hoofd_idx   = el['paginas'][0]
            vervolg_idx = el['paginas'][1:]

            extra_regels = []
            for vi in vervolg_idx:
                extra_regels.extend(pv.extraheer_regels_vervolgblad(vb_doc[vi]))

            hoofd = vb_doc[hoofd_idx]

            # PM-maaten + maatvervanging in tekening (gecombineerd)
            pm = pm_invoer.get(hoofd_idx, {})
            try:
                b_pm = int(pm.get('breedte') or 0)
                h_pm = int(pm.get('hoogte')  or 0)
            except ValueError:
                b_pm = h_pm = 0

            if b_pm and h_pm:
                pv.schrijf_pm_maat(hoofd, b_pm, h_pm)

                # Vervang offer-maat door PM-maat in tekening (alleen als afwijkend)
                spec = specs[hoofd_idx]
                b_oud = spec.get('offer_breedte')
                h_oud = spec.get('offer_hoogte')
                if b_oud and b_pm != b_oud:
                    try:
                        pv.wijzig_maat_in_tekening(hoofd, int(b_oud), b_pm, zone='bottom')
                    except Exception:
                        pass
                if h_oud and h_pm != h_oud:
                    try:
                        pv.wijzig_maat_in_tekening(hoofd, int(h_oud), h_pm, zone='right')
                    except Exception:
                        pass

            # Afwijkingen bepalen + acties toepassen
            afwijkingen_raw = pv.zoek_afwijkingen(specs[hoofd_idx], groep_spec)
            afwijkingen_rood = []   # ongewijzigd → rood
            genegeerde_afw   = []   # bewust afwijkend → groen
            gewijzigde_afw   = []   # aangepaste tekst → oranje

            for a in afwijkingen_raw:
                actie = afw_acties.get((hoofd_idx, a))
                if actie is None:
                    afwijkingen_rood.append(a)
                elif actie[0] == 'genegeerd':
                    genegeerde_afw.append(a)
                elif actie[0] == 'aangepast':
                    pass  # volledig weglaten
                elif actie[0] == 'gewijzigd':
                    gewijzigde_afw.append(actie[1])

            pv.process_volgblad(
                hoofd,
                afwijkingen_rood,
                extra_regels=extra_regels,
                genegeerde_afw=genegeerde_afw,
                gewijzigde_afw=gewijzigde_afw,
            )

            for _ in range(stuks):
                result.insert_pdf(vb_doc, from_page=hoofd_idx, to_page=hoofd_idx)

    pv.voeg_paginanummers_toe(result)

    buf = io.BytesIO()
    result.save(buf)
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def _render_pages(data: bytes, scale: float = 1.3):
    doc = fitz.open(stream=data, filetype="pdf")
    mat = fitz.Matrix(scale, scale)
    return [doc[i].get_pixmap(matrix=mat).tobytes("png") for i in range(len(doc))]


# ── Titel ─────────────────────────────────────────────────────────────────────
st.title("🏠 Voorbladen invullen")
st.caption("Belisol PVC CERTIX — upload de volgbladen, de app genereert automatisch de voorbladen")

left, right = st.columns([2, 3], gap="large")

# ══════════════════════════════════════════════════════════════════════════════
# LINKER KOLOM — controls
# ══════════════════════════════════════════════════════════════════════════════
with left:
    st.divider()

    # 1. Upload ────────────────────────────────────────────────────────────────
    uploaded = st.file_uploader(
        "Upload volgbladen PDF",
        type="pdf",
        help="PDF met alleen de volgbladen (technische fiches per element)",
    )

    if uploaded is not None:
        if st.session_state.last_upload_name != uploaded.name:
            st.session_state.preview_page     = 0
            st.session_state.last_upload_name = uploaded.name
            st.session_state.afw_acties       = {}   # reset bij nieuw bestand
    else:
        st.session_state.last_upload_name = None

    if uploaded is None:
        st.info("Upload een PDF met volgbladen om te beginnen.")

    else:
        pdf_bytes = uploaded.getvalue()
        header, specs, elementen, groepen = _parse(pdf_bytes)

        if not specs:
            st.error("Geen volgbladen gevonden in dit PDF.")

        else:
            # 2. Samenvatting ──────────────────────────────────────────────────
            st.subheader("📋 Gevonden elementen")

            for groep_naam, groep_idx in groepen:
                groep_idx_set   = set(groep_idx)
                groep_specs     = [specs[i] for i in groep_idx]
                groep_spec      = pv.bepaal_groep_spec(groep_specs)
                groep_elementen = [el for el in elementen if el['paginas'][0] in groep_idx_set]
                n_stuks_totaal  = sum(el['spec'].get('stuks', 1) for el in groep_elementen)

                with st.expander(
                    f"**{groep_naam}** — {len(groep_elementen)} element(en), "
                    f"{n_stuks_totaal} stuk(s) totaal → 1 voorblad",
                    expanded=True,
                ):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Glas",        groep_spec.get("glas_str")     or "—")
                    c2.metric("Profiel",     groep_spec.get("profiel_type") or "—")
                    c3.metric("Kleur kader", groep_spec.get("kader_buiten") or "—")

                    for el in groep_elementen:
                        i     = el['paginas'][0]
                        stuks = el['spec'].get('stuks', 1)
                        afw   = pv.zoek_afwijkingen(el['spec'], groep_spec)

                        doc_tmp = fitz.open(stream=pdf_bytes, filetype="pdf")
                        regels  = [r.strip() for r in doc_tmp[i].get_text("text").split("\n") if r.strip()]
                        label   = next((r for r in regels if r.startswith("POS.")), f"Volgblad {i+1}")
                        label_met_stuks = f"{label}  ×{stuks}" if stuks > 1 else label
                        n_verv  = len(el['paginas']) - 1

                        if not afw:
                            extra = f"  _(+{n_verv} vervolgblad)_" if n_verv else ""
                            st.caption(f"✓ {label_met_stuks} — conform voorblad{extra}")
                            continue

                        # ── Element met afwijkingen ─────────────────────────
                        extra_lbl = f"  _(+{n_verv} vervolgblad)_" if n_verv else ""
                        st.markdown(f"**⚠️ {label_met_stuks}**{extra_lbl}")

                        for lbl in afw:
                            lbl_key = f"{i}__{lbl[:40].replace(' ','_').replace('/','_')}"
                            actie   = st.session_state.afw_acties.get((i, lbl))

                            if actie and actie[0] != 'wijzigen_actief':
                                # Toon huidige status + ongedaan-knop
                                status, tekst = actie
                                if status == 'genegeerd':
                                    st.success(f"✓ **{lbl}** — bewust afwijkend")
                                elif status == 'aangepast':
                                    st.error(f"✗ **{lbl}** — wordt aangepast aan voorblad")
                                elif status == 'gewijzigd':
                                    st.warning(f'✏️ **{lbl}** → *"{tekst}"*')
                                if st.button("↩ Ongedaan", key=f"undo_{lbl_key}",
                                             use_container_width=False):
                                    del st.session_state.afw_acties[(i, lbl)]
                                    st.rerun()

                            elif actie and actie[0] == 'wijzigen_actief':
                                # Toon tekstveld om nieuwe tekst in te voeren
                                st.warning(f"✏️ **{lbl}** — voer aangepaste tekst in:")
                                nieuwe_tekst = st.text_input(
                                    "Nieuwe tekst", value=actie[1],
                                    key=f"txt_{lbl_key}", label_visibility="collapsed"
                                )
                                col_ok, col_ann = st.columns(2)
                                if col_ok.button("✔ Opslaan", key=f"ok_{lbl_key}",
                                                 use_container_width=True):
                                    st.session_state.afw_acties[(i, lbl)] = ('gewijzigd', nieuwe_tekst)
                                    st.rerun()
                                if col_ann.button("✖ Annuleren", key=f"ann_{lbl_key}",
                                                  use_container_width=True):
                                    del st.session_state.afw_acties[(i, lbl)]
                                    st.rerun()

                            else:
                                # Geen actie → toon de afwijking + 3 knoppen
                                st.markdown(
                                    f"<span style='color:#cc3300'>⚠ {lbl}</span>",
                                    unsafe_allow_html=True,
                                )
                                bn1, bn2, bn3 = st.columns(3)
                                if bn1.button("✓ Negeren", key=f"neg_{lbl_key}",
                                              use_container_width=True,
                                              help="Markeer als bewust afwijkend (groen)"):
                                    st.session_state.afw_acties[(i, lbl)] = ('genegeerd', '')
                                    st.rerun()
                                if bn2.button("✗ Aanpassen", key=f"aap_{lbl_key}",
                                              use_container_width=True,
                                              help="Verwijder afwijking (conform voorblad)"):
                                    st.session_state.afw_acties[(i, lbl)] = ('aangepast', '')
                                    st.rerun()
                                if bn3.button("✏️ Wijzigen", key=f"wij_{lbl_key}",
                                              use_container_width=True,
                                              help="Schrijf een aangepaste tekst"):
                                    st.session_state.afw_acties[(i, lbl)] = ('wijzigen_actief', '')
                                    st.rerun()

            # ── Mutatie-overzicht ──────────────────────────────────────────────
            acties_actief = {
                k: v for k, v in st.session_state.afw_acties.items()
                if v[0] != 'wijzigen_actief'
            }
            if acties_actief:
                st.divider()
                st.subheader("📝 Mutaties")
                for (ei, lbl), (status, tekst) in sorted(acties_actief.items()):
                    doc_tmp = fitz.open(stream=pdf_bytes, filetype="pdf")
                    regels  = [r.strip() for r in doc_tmp[ei].get_text("text").split("\n") if r.strip()]
                    pos     = next((r for r in regels if r.startswith("POS.")), f"Volgblad {ei+1}")
                    if status == 'genegeerd':
                        st.success(f"✓ **{pos}** — *{lbl}*: bewust afwijkend")
                    elif status == 'aangepast':
                        st.error(f"✗ **{pos}** — *{lbl}*: conform voorblad")
                    elif status == 'gewijzigd':
                        st.warning(f'✏️ **{pos}** — *{lbl}* → "{tekst}"')

            st.divider()

            # 3. Productiemaaten ───────────────────────────────────────────────
            st.subheader("📐 Productiemaaten (PM)")
            st.caption(
                "Voer de **globale** maatvoering in per element (mm). "
                "Verdeelmaten op tekeningen _niet_ als PM opgeven. "
                "De tekening wordt automatisch bijgewerkt als de PM afwijkt van de offermaat."
            )

            pm_invoer: dict[int, dict] = {}
            for el in elementen:
                if el['spec'].get('is_vervolgblad'):
                    continue
                i            = el['paginas'][0]
                spec         = specs[i]
                breedte_hint = spec.get('offer_breedte')
                hoogte_hint  = spec.get('offer_hoogte')

                doc_tmp = fitz.open(stream=pdf_bytes, filetype="pdf")
                regels  = [r.strip() for r in doc_tmp[i].get_text("text").split("\n") if r.strip()]
                label   = next((r for r in regels if r.startswith("POS.")), f"Volgblad {i+1}")

                b_ph = str(breedte_hint) if breedte_hint else "breedte (mm)"
                h_ph = str(hoogte_hint)  if hoogte_hint  else "hoogte (mm)"

                cc1, cc2, cc3 = st.columns([3, 2, 2])
                cc1.markdown(f"**{label}**")
                b = cc2.text_input("B (mm)", key=f"pm_b_{i}", placeholder=b_ph,
                                   label_visibility="collapsed")
                h = cc3.text_input("H (mm)", key=f"pm_h_{i}", placeholder=h_ph,
                                   label_visibility="collapsed")
                pm_invoer[i] = {"breedte": b.strip(), "hoogte": h.strip()}

            st.divider()

            # 4. Auto-genereren ───────────────────────────────────────────────
            pm_frozen = tuple(sorted(
                (k, d['breedte'], d['hoogte']) for k, d in pm_invoer.items()
            ))
            afw_acties_frozen = tuple(sorted(
                (ei, lbl, status, tekst)
                for (ei, lbl), (status, tekst) in st.session_state.afw_acties.items()
                if status != 'wijzigen_actief'
            ))
            generated_bytes = _genereer(pdf_bytes, pm_frozen, afw_acties_frozen)


# ══════════════════════════════════════════════════════════════════════════════
# RECHTER KOLOM — live preview
# ══════════════════════════════════════════════════════════════════════════════
with right:
    if uploaded is not None and specs and generated_bytes is not None:
        pages   = _render_pages(generated_bytes)
        n_pages = len(pages)
        output_naam = Path(uploaded.name).stem + "_ingevuld.pdf"

        # Titelrij: label links, download rechts ───────────────────────────────
        hdr1, hdr2 = st.columns([3, 2])
        hdr1.subheader("📄 Preview — Ingevuld PDF")
        hdr2.download_button(
            label="⬇️ Download ingevuld PDF",
            data=generated_bytes,
            file_name=output_naam,
            mime="application/pdf",
            use_container_width=True,
            type="primary",
            key="dl_btn",
        )

        # Hoogte van één pagina uit de PNG-header lezen (bytes 20-24 = height uint32 BE)
        import struct
        _page_h = struct.unpack('>I', pages[0][20:24])[0]   # pixelhoogte van één pagina
        _nav_h  = 42                                          # navigatiebalk
        _component_h = _page_h + _nav_h + 6                  # iframe-hoogte

        # Zelfstandige HTML-preview met eigen navigatie + toetsenbord ─────────
        imgs_html = '\n'.join(
            f'<div class="pw" id="p{i}">'
            f'<img src="data:image/png;base64,{base64.b64encode(pg).decode()}">'
            f'<div class="cap">Pagina {i+1} / {n_pages}</div>'
            f'</div>'
            for i, pg in enumerate(pages)
        )

        components.html(
            f"""<!DOCTYPE html><html><head><meta charset="utf-8">
            <style>
            *{{box-sizing:border-box;margin:0;padding:0}}
            body{{font-family:sans-serif;background:transparent}}
            #nav{{display:flex;align-items:center;gap:6px;padding:0 0 6px}}
            #nav button{{padding:4px 14px;cursor:pointer;border:1px solid #ccc;
                         border-radius:4px;background:#f0f2f6;font-size:15px}}
            #nav button:disabled{{opacity:.35;cursor:default}}
            #nav button:hover:not(:disabled){{background:#dde}}
            #ind{{flex:1;text-align:center;color:#555;font-size:13px}}
            #box{{height:{_page_h}px;overflow-y:auto;border:1px solid #ddd;
                  border-radius:6px;background:#f8f8f8;scroll-behavior:auto}}
            .pw{{margin:0 4px 6px;padding:3px;border-radius:4px;
                 transition:outline .1s}}
            .pw.on{{outline:3px solid #1f77b4}}
            .pw img{{width:100%;display:block;border-radius:2px}}
            .cap{{text-align:center;color:#999;font-size:11px;padding:2px 0}}
            </style></head><body>
            <div id="nav">
              <button id="prv" onclick="go(-1)" disabled>◀</button>
              <span id="ind">Pagina 1 / {n_pages}</span>
              <button id="nxt" onclick="go(1)">▶</button>
            </div>
            <div id="box">{imgs_html}</div>
            <script>
            var pages=[],cur=0,n={n_pages};
            function upd(){{
              document.getElementById('prv').disabled=(cur===0);
              document.getElementById('nxt').disabled=(cur===n-1);
              document.getElementById('ind').textContent='Pagina '+(cur+1)+' / '+n;
              pages.forEach(function(p,i){{p.classList.toggle('on',i===cur)}});
            }}
            function go(d){{
              var nx=Math.max(0,Math.min(n-1,cur+d));
              if(nx===cur)return;
              cur=nx;
              var box=document.getElementById('box');
              box.scrollTop=pages[cur].offsetTop-4;
              upd();
            }}
            document.addEventListener('keydown',function(e){{
              if(e.key==='ArrowRight'||e.key==='ArrowDown'){{go(1);e.preventDefault();}}
              if(e.key==='ArrowLeft' ||e.key==='ArrowUp')  {{go(-1);e.preventDefault();}}
            }});
            document.getElementById('box').addEventListener('scroll',function(){{
              var top=this.scrollTop,best=0;
              pages.forEach(function(p,i){{if(p.offsetTop-8<=top)best=i;}});
              if(best!==cur){{cur=best;upd();}}
            }});
            window.onload=function(){{
              pages=Array.from(document.querySelectorAll('.pw'));
              upd();
            }};
            </script></body></html>""",
            height=_component_h,
            scrolling=False,
        )

    elif uploaded is not None:
        st.info("Preview wordt geladen…")
