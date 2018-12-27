import optparse
import sys
import csv
import score
import random
from collections import defaultdict
import numpy as np
import paraphrase as pp
import pickle as pkl
import json
import pandas
import traceback

RAND_ITER = 5

#####################
# VEC_FILES
#
# These contain some PPDB data to enable you to run clustering on the provided
# example paraphrase files. They are pickle files storing dictionaries with
# the structures:
# { target : { paraphrase : score } } (for PPDB2.0Score and Independent)
# { target : np.ndarray } (for word2vec)
#
# If you want to use your own similarity data, replace these with your own
# dictionaries
VEC_FILES = {'PPDB2.0Score': '../data/ppdb_data/pp_samestems_xxl_PPDB2.0Score.p',
             'Independent': '../data/ppdb_data/pp_samestems_xxl_Independent.p',
             # contains non-entailment probability, p(Independent)
             'word2vec': '../data/ppdb_data/GoogleNews-vectors-negative300.p'}


def create_weighted_scores(data_frame, weighted_factor, column_name):
    data_frame['{}*{}'.format(column_name, weighted_factor)] = data_frame[column_name] * data_frame[weighted_factor]
    return data_frame['{}*{}'.format(column_name, weighted_factor)].sum() / data_frame[weighted_factor].sum()


def get_evaluation_results(df):
    # df['Gold_Length-Actual_Length'] = df['Gold Length'] - df['Actual Length']
    # df['Gold_Length-Actual_Length'] = df['Gold_Length-Actual_Length'].abs()
    data = {
        'Number of Words': len(df.index),
        'F Score': create_weighted_scores(df, 'Gold Length', 'F Score'),
        'V Measure': create_weighted_scores(df, 'Gold Length', 'V Measure'),
        'Precision': create_weighted_scores(df, 'Gold Length', 'Precision'),
        'Recall': create_weighted_scores(df, 'Gold Length', 'Recall'),
        'Homogeneity': create_weighted_scores(df, 'Gold Length', 'Homogeneity'),
        'Completeness': create_weighted_scores(df, 'Gold Length', 'Completeness'),
        'Gold Length': df['Gold Length'].mean(),
        # 'Actual Length': df['Actual Length'].mean(),
        # 'Gold Length - Actual Length Mean': df['Gold_Length-Actual_Length'].mean(),
        # 'Gold Length - Actual Length Std': df['Gold_Length-Actual_Length'].std(),
        # 'Actual Length Std': df['Actual Length'].std(),
        # 'Remaining Actual': df['Remaining Actual'].mean(),
        # 'Remaining Gold': df['Remaining Gold'].mean(),
    }

    for key, value in data.items():
        print('\t{}: {:.2f}'.format(key, value))

    return data


def jdefault(obj):
    if isinstance(obj, set):
        return list(obj)
    return obj.__dict__


def chunk(seq, num):
    avg = len(seq) / float(num)
    out = []
    last = 0.0

    while last < len(seq):
        out.append(seq[int(last):int(last + avg)])
        last += avg

    return out


if __name__ == "__main__":
    optparser = optparse.OptionParser()
    optparser.add_option("-p", "--ppfile", dest="ppfile",
                         default='../data/pp/semeval_tgtlist_rand80_multiword_xxl_PPDB2.0Score_plusself.ppsets',
                         help="Paraphrase file")
    optparser.add_option("-s", "--score", dest="goldfile", default='../data/gold/crowd_eval_targets.crowdgold',
                         help="Score against specified gold file.")
    optparser.add_option("-o", "--outfile", dest="outfile", default='results.csv', help="Results file")
    optparser.add_option("-b", "--baselines", action="store_true", default=False, help="Run baseline tests")
    optparser.add_option("-f", "--filter", action="store_true", default=False,
                         help="Filter paraphrase sets by gold before clustering")
    optparser.add_option("-m", "--method", dest="method", default="hgfc",
                         help="Clustering method ('spectral', 'semclust', or 'hgfc')")
    (opts, _) = optparser.parse_args()

    if opts.ppfile is None:
        sys.stderr.write('Provide paraphrase sets file using -p flag\n')
        exit(0)

    if opts.method not in ['hgfc', 'spectral', 'semclust']:
        sys.stderr.write("Unknown clustering method %s specified. "
                         "Please choose 'spectral', 'semclust', or 'hgfc'\n" % opts.method)
        exit(0)

    entail = True

    #################################
    # Cluster target words
    #################################

    # Read in paraphrase file
    sys.stderr.write('Reading paraphrase file...')
    ppsets = pp.read_pps(opts.ppfile)
    sys.stderr.write('done\n')

    # If scoring and pre-filtering, shrink paraphrase sets to gold file lexicon
    if opts.goldfile is not None and opts.filter:
        sys.stderr.write('Filtering paraphrase sets by gold data...')
        for wt, ppset in ppsets.items():
            ppset.filter_ppset_by_gold(opts.goldfile)
        sys.stderr.write('done\n')

    # Load vectors
    sys.stderr.write('Loading vectors...')
    with open(VEC_FILES['word2vec'], 'rb') as fin:
        vecreps = pkl.load(fin, encoding='latin1')
    for wt, ppset in ppsets.items():
        ppset.load_vecs(vecreps)
    del vecreps
    sys.stderr.write('done\n')

    # Load entailments
    if entail:
        sys.stderr.write('Loading entailment data...')
        with open(VEC_FILES['Independent'], 'rb') as fin:
            _, _, w2e = pkl.load(fin, encoding='latin1')
        sys.stderr.write('done\n')

    # Load PPDB scores
    sys.stderr.write('Loading PPDB2.0Score data...')
    with open(VEC_FILES['PPDB2.0Score'], 'rb') as fin:
        _, _, w2p = pkl.load(fin, encoding='latin1')
    sys.stderr.write('done\n')

    # Cluster vectors
    sys.stderr.write('Clustering paraphrases...\n')
    results_json = {}
    for i, (wt, ppset) in enumerate(ppsets.items()):
        print(i, wt.word)
        try:
            # Baseline: SEM-CLUST
            if opts.method == 'semclust':
                wlst, x = ppset.vec_matrix()
                distrib_sims = dict(zip(wlst, x))
                ppset.sem_clust(w2p, distrib_sims)

            # Method 1: Spectral clustering w/ Local Scaling
            if opts.method == 'spectral':
                ppset.zmp_cluster(w2p, w2e)

            # Method 2: HGFC
            if opts.method == 'hgfc':
                ppset.hgfc_cluster(w2p, w2e)

            results_json['.'.join([wt.word, wt.type])] = ppset.sense_clustering
        except Exception as e:

            traceback.print_tb(e.__traceback__)
            print(wt)

    # print(json.dumps(results_json, indent=2, default=jdefault))

    #################################
    # Score clustering solution
    #################################
    scores = {}
    errors = []
    headers = ['Word', 'POS', 'F Score', 'Precision', 'Recall', 'V Measure', 'Homogeneity', 'Completeness', 'Gold Length',
               'Gold Solution', 'Actual Solution',
               'Rand_VMeas', 'Rand_FScore', 'MFS_VMeas', 'MFS_FScore', '1c1par_VMeas', '1c1par_FScore']
    if opts.goldfile is not None:
        gold = pp.read_gold(opts.goldfile)
        for wt, ppset in ppsets.items():
            scores[wt] = {}
            baseline_rand_vmeas = 0.0
            baseline_rand_fscore = 0.0
            baseline_mfs_vmeas = 0.0
            baseline_mfs_fscore = 0.0
            baseline_1c1par_vmeas = 0.0
            baseline_1c1par_fscore = 0.0
            try:
                tgtname = '_'.join([wt.word, wt.type])
                sol = ppset.sense_clustering
                tgtset = set([item for sublist in sol.values() for item in sublist])

                gld = gold[wt].sense_clustering
                goldset = set([item for sublist in gld.values() for item in sublist])

                gldfilt = defaultdict(set,
                                      {n: l & tgtset for n, l in gld.items() if len(l & tgtset) > 0})  # remove empties
                gldfiltnodup = defaultdict(set)  # remove duplicate classes
                for k, s in gldfilt.items():
                    if frozenset(s) not in gldfiltnodup.items():
                        gldfiltnodup[k] = frozenset(s)

                solfilt = defaultdict(set, {n: l & goldset for n, l in sol.items() if
                                            len(l & goldset) > 0})  # remove empties
                solfiltnodup = defaultdict(set)  # remove duplicate classes
                for k, s in solfilt.items():
                    if frozenset(s) not in solfiltnodup.items():
                        solfiltnodup[k] = frozenset(s)

                print(gldfilt)
                print(solfilt)

                fscore, prec, rec, vmeas, hom, comp = \
                    score.score_clustering_solution(tgtname,
                                                    solfilt,
                                                    gldfilt,
                                                    tempdir='../eval/semeval_unsup_eval/keys')

                print(fscore)
                print(prec)

                if opts.baselines:
                    ## Most Frequent Sense (MFS) Baseline
                    mfs = {1: tgtset}
                    baseline_mfs_fscore, _, _, baseline_mfs_vmeas, h, c = \
                        score.score_clustering_solution(tgtname, mfs, gldfilt,
                                                        tempdir='../eval/semeval_unsup_eval/keys')
                    ## 1 Cluster per Paraphrase Baseline
                    onec1par = {k: set([v]) for (k, v) in enumerate(tgtset)}
                    baseline_1c1par_fscore, _, _, baseline_1c1par_vmeas, h, c = \
                        score.score_clustering_solution(tgtname, onec1par, gldfilt,
                                                        tempdir='../eval/semeval_unsup_eval/keys')
                    ## Random clusters baseline
                    random.seed(0)
                    tgtlist = list(tgtset)
                    rand_vmeas = []
                    rand_fscores = []
                    for i in range(RAND_ITER):
                        random.shuffle(tgtlist)
                        randsol = dict(enumerate(chunk(tgtlist, RAND_ITER)))
                        rand_f, _, _, rand_v, _, _ = \
                            score.score_clustering_solution(tgtname, randsol, gldfilt,
                                                            tempdir='../eval/semeval_unsup_eval/keys')
                        rand_vmeas.append(rand_v)
                        rand_fscores.append(rand_f)
                    print(rand_vmeas)
                    print(rand_fscores)
                    baseline_rand_fscore = np.mean(rand_fscores)
                    baseline_rand_vmeas = np.mean(rand_vmeas)

                gldsize = len([n for n, l in gld.items() if len(l & tgtset) > 0])
                scores[wt] = dict(zip(headers,
                                      [wt.word, wt.type, fscore, prec, rec, vmeas, hom, comp, gldsize, gldfilt, solfilt,
                                       baseline_rand_vmeas, baseline_rand_fscore, baseline_mfs_vmeas,
                                       baseline_mfs_fscore, baseline_1c1par_vmeas, baseline_1c1par_fscore]))
                print('Scores for',
                      tgtname + ':',
                      {h: scores[wt][h] for h in ['F Score', 'Precision', 'Recall', 'V Measure', 'Homogeneity', 'Completeness']})
            except Exception as e:
                print('SCORING ERROR:', e)
                print(wt)
                errors.append(wt)
        print('Words with scoring errors:', errors)
        with open(opts.outfile, 'w') as fout:
            writ = csv.DictWriter(fout, fieldnames=headers)

            writ.writeheader()
            for sc in scores.values():
                writ.writerow(sc)

        with open(opts.outfile, 'r') as fin:
            df = pandas.read_csv(fin, sep=',')
            final_data = get_evaluation_results(df)


