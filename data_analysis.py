import pandas as pd
import numpy as np

def analyser_donnees(df):
    lignes, colonnes_n = df.shape
    if lignes == 0 or colonnes_n == 0:
        raise ValueError('La table ne contient aucune donnée analysable.')
    manque = df.isna().sum()
    total_manquantes = int(manque.sum())
    doublons = int(df.duplicated().sum())
    completude = round((1 - total_manquantes/(lignes * colonnes_n))*100, 2)
    unicite = round((1 - doublons/lignes)*100, 2)
    anomalies = {}
    for colonne in df.select_dtypes(include=[np.number]).columns:
        valeurs = df[colonne].dropna()
        if len(valeurs) < 4:
            anomalies[str(colonne)] = 0
            continue
        q1, q3 = valeurs.quantile(.25), valeurs.quantile(.75)
        iqr = q3-q1
        anomalies[str(colonne)] = int(((valeurs < q1-1.5*iqr) | (valeurs > q3+1.5*iqr)).sum()) if iqr > 0 else 0
    colonnes = [{'nom': str(nom), 'type': str(df[nom].dtype),
                 'valeurs_manquantes': int(df[nom].isna().sum()),
                 'valeurs_uniques': int(df[nom].nunique(dropna=True)),
                 'taux_completude': round(float(df[nom].notna().mean())*100, 2)}
                for nom in df.columns]
    return {'nb_lignes': lignes, 'nb_colonnes': colonnes_n,
            'total_manquantes': total_manquantes, 'nb_doublons': doublons,
            'taux_completude': completude, 'taux_unicite': unicite,
            'score_qualite': round((completude+unicite)/2, 2),
            'anomalies': anomalies, 'colonnes': colonnes}
