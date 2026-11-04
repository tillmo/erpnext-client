// Client Script "Sales Invoice-Form" (DocType Sales Invoice, view Form) - reference copy.
// Balkonmodul invoices go to project PROJ-0051 with stock update, VAT 0 % and payment terms BKW.
// SBKW (subsidised balcony power plants) are balcony modules, so ticking SBKW ticks Balkonmodul.
// Material invoices without a PreRechnung for a direct delivery need a stock update.
frappe.ui.form.on("Sales Invoice", {
    refresh: function(frm) {
        frm.trigger("set_balkonmodul");
        frm.trigger("set_update_stock");
        frm.trigger("check_update_stock");
    },
    custom_sbkw: function(frm) {
        frm.trigger("set_balkonmodul");
    },
    balkonmodul: function(frm) {
        frm.trigger("set_update_stock");
    },
    set_balkonmodul(frm) {
        if(frm.doc.docstatus === 0){
            if(frm.doc.custom_sbkw && !frm.doc.balkonmodul){
                alert("Balkonmodul angewählt, da SBKW");
                frm.set_value("balkonmodul", 1);
                frm.trigger("set_update_stock");
            }
        }
    },
    set_update_stock(frm) {
        if(frm.doc.docstatus === 0){
            if(frm.doc.balkonmodul){
                if (frm.doc.project!="PROJ-0051"){
                    alert("Projekt PROJ-0051 angewählt, da Balkonmodule");
                    frm.set_value("project", "PROJ-0051");
                }
                if (!frm.doc.update_stock){
                    alert("Lagerhaltung angewählt, da Balkonmodule");
                    frm.set_value("update_stock", "1");
                }
                frm.set_value("taxes_and_charges", "Germany VAT 0% - SoMiKo");
                frm.set_value("payment_terms_template", "BKW");
            }
        }
    },
    check_update_stock(frm) {
        if(frm.doc.docstatus === 0){
            if(frm.doc.update_stock === 0 && frm.doc.material && !frm.doc.custom_prerechnung){
                frm.set_value("update_stock", 1);
                alert("Lagerhaltung angewählt, da keine PreRechnung für Direktlieferung eingetragen wurde.");
            }
        }
    },
    set_material(frm) {
        if(frm.doc.docstatus === 0){
            if(frm.doc.material){
                frm.set_value("project", "PROJ-0052");
                frm.set_value("taxes_and_charges", "Germany VAT 19% - SoMiKo");
            }
        }
    }
});
