"""Names and definitions transcribed from UKB-KG manuscript Table 1 (R2)."""
ENTITY_TYPES = [
 ('GENE','Genes & Molecular Sequences','Gene or genome; molecular, nucleotide, amino acid, and carbohydrate sequences.'),
 ('MEAS','Measurements','Clinical findings, laboratory/test results, and measurable attributes of an organism.'),
 ('DISO','Disorders','Disease or syndrome; abnormalities; injury or poisoning; pathologic dysfunction; signs and symptoms.'),
 ('PHYS','Physiology','Biologic/physiologic functions and organism/tissue/cell-level functions.'),
 ('PROC','Procedures','Procedures in healthcare, diagnosis, laboratory testing, therapy, and research.'),
 ('CHEM','Chemicals & Drugs','Chemicals; pharmacologic/biologically active substances; hormones, enzymes, vitamins; hazardous substances; clinical drugs.'),
 ('MISC','Miscellaneous','Miscellaneous entities, such as concepts, living beings, objects, devices.'),
 ('ANAT','Anatomy','Anatomical structures and regions; body systems/organs; tissues; cells and cell components.'),
 ('ACTI','Activities & Behaviors & Phenomena','Activities, behaviors and phenomena. Many lifestyle and exposure factors are included here.'),
 ('BASE','Baseline Demographic Concepts','Concepts related to demographic and population characteristics, such as age, population groups, and patient groups.'),
]
TYPE_NAMES = {code:name for code,name,_ in ENTITY_TYPES}


def definition_rows(counts):
    total=sum(counts.values())
    rows=[{'Abbr':code,'Entity Type':name,
           'Count':f'{counts.get(code,0):,} ({counts.get(code,0)/total:.1%})' if total else '0 (0.0%)',
           'Description':description} for code,name,description in ENTITY_TYPES]
    rows.append({'Abbr':'Total','Entity Type':'','Count':f'{total:,}','Description':''})
    return rows
