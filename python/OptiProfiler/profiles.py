import os
import re
import shutil
import warnings
from contextlib import redirect_stderr, redirect_stdout, suppress
from datetime import datetime
from inspect import signature
from pathlib import Path

import numpy as np
from cycler import cycler
from joblib import Parallel, delayed
from matplotlib import pyplot as plt
from matplotlib.backends import backend_pdf
from matplotlib.ticker import MaxNLocator

from .features import Feature
from .problems import Problem, FeaturedProblem, load_cutest_problem
from .settings import FeatureName, ProfileOptionKey, CUTEstProblemOptionKey, FeatureOptionKey, ProblemError
from .utils import get_logger


def create_profiles(solvers, labels=(), cutest_problem_names=(), extra_problems=(), feature_name='plain', **kwargs):
    # Preprocess the solvers.
    if not hasattr(solvers, '__len__') or not all(callable(solver) for solver in solvers):
        raise TypeError('The solvers must be a list of callables.')
    if len(solvers) < 2:
        raise ValueError('At least two solvers must be given.')
    solvers = list(solvers)

    # Preprocess the labels.
    if not hasattr(labels, '__len__') or not all(isinstance(label, str) for label in labels):
        raise TypeError('The labels must be a list of strings.')
    if len(labels) not in [0, len(solvers)]:
        raise ValueError('The number of labels must equal the number of solvers.')
    labels = list(labels)
    if len(labels) == 0:
        labels = [solver.__name__ for solver in solvers]

    # Preprocess the CUTEst problem names.
    if not hasattr(cutest_problem_names, '__len__') or not all(isinstance(problem_name, str) for problem_name in cutest_problem_names):
        raise TypeError('The CUTEst problem names must be a list of strings.')
    cutest_problem_names = list(cutest_problem_names)

    # Preprocess the extra problems.
    if not hasattr(extra_problems, '__len__') or not all(isinstance(problem, Problem) for problem in extra_problems):
        raise TypeError('The extra problems must be a list of problems.')
    extra_problems = list(extra_problems)

    # Check that the number of problems is satisfactory.
    if len(cutest_problem_names) + len(extra_problems) < 1:
        raise ValueError('At least one problem must be given.')

    # Build the feature.
    logger = get_logger(__name__)
    feature = Feature(feature_name)
    logger.info(f'Starting the computation of the {feature.name} profiles.')

    # Get the different options from the keyword arguments.
    feature_options = {}
    cutest_problem_options = {}
    profile_options = {}
    for key, value in kwargs.items():
        if key in FeatureOptionKey.__members__.values():
            feature_options[key] = value
        elif key in CUTEstProblemOptionKey.__members__.values():
            cutest_problem_options[key] = value
        elif key in ProfileOptionKey.__members__.values():
            profile_options[key] = value
        else:
            raise ValueError(f'Unknown option: {key}.')

    # Set the default profile options.
    profile_options.setdefault(ProfileOptionKey.N_JOBS.value, -1)
    profile_options.setdefault(ProfileOptionKey.BENCHMARK_ID.value, '.')

    # Check whether the profile options are valid.
    if isinstance(profile_options[ProfileOptionKey.N_JOBS], float) and profile_options[ProfileOptionKey.N_JOBS].is_integer():
        profile_options[ProfileOptionKey.N_JOBS] = int(profile_options[ProfileOptionKey.N_JOBS])
    if not isinstance(profile_options[ProfileOptionKey.N_JOBS], int):
        raise TypeError(f'Option {ProfileOptionKey.N_JOBS} must be an integer.')
    if not isinstance(profile_options[ProfileOptionKey.BENCHMARK_ID], str):
        raise TypeError(f'Option {ProfileOptionKey.BENCHMARK_ID} must be a string.')

    # Solve the problems.
    max_eval_factor = 500
    fun_values, maxcv_values, fun_init, maxcv_init, n_eval, problem_names, problem_dimensions = _solve_all(cutest_problem_names, cutest_problem_options, extra_problems, solvers, labels, feature, max_eval_factor, profile_options)
    merit_values = _compute_merit_values(fun_values, maxcv_values)
    merit_init = _compute_merit_values(fun_init, maxcv_init)

    # Determine the least merit value for each problem.
    merit_min = np.min(merit_values, (1, 2, 3))
    if feature.name in [FeatureName.NOISY, FeatureName.TOUGH, FeatureName.TRUNCATED]:
        feature_plain = Feature('plain')
        logger.info(f'Starting the computation of the plain profiles.')
        fun_values_plain, maxcv_values_plain, _, _, _, _, _ = _solve_all(cutest_problem_names, cutest_problem_options, extra_problems, solvers, labels, feature_plain, max_eval_factor, profile_options)
        merit_values_plain = _compute_merit_values(fun_values_plain, maxcv_values_plain)
        merit_min_plain = np.min(merit_values_plain, (1, 2, 3))
        merit_min = np.minimum(merit_min, merit_min_plain)

    # Paths to the results.
    path_out = Path('out', feature.name, profile_options[ProfileOptionKey.BENCHMARK_ID]).resolve()
    path_out.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().astimezone().strftime('%Y-%m-%dT%H-%M-%SZ')
    path_pdf_perf = path_out / f'perf_{timestamp}.pdf'
    path_pdf_data = path_out / f'data_{timestamp}.pdf'
    path_pdf_log_ratio = path_out / f'log-ratio_{timestamp}.pdf'
    path_txt_problems = path_out / f'problems_{timestamp}.txt'

    # Store the names of the problems.
    with path_txt_problems.open('w') as f:
        f.write(os.linesep.join(problem_names))

    # Set up matplotlib for plotting the profiles.
    logger.info('Creating results.')
    prop_cycle = cycler(color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'])
    prop_cycle += cycler(linestyle=[(0, ()), (0, (1, 1.5)), (0, (3, 1.5)), (0, (5, 1.5, 1, 1.5)), (0, (5, 1.5, 1, 1.5, 1, 1.5)), (0, (1, 3)), (0, (3, 3)), (0, (5, 3, 1, 3)), (0, (5, 3, 1, 3, 1, 3)), (0, (1, 4.5))])
    with plt.rc_context({
        'axes.prop_cycle': prop_cycle,
        'font.family': 'serif',
        'font.size': 16,
        'text.usetex': True if shutil.which('latex') else False,
    }):
        # Create the performance and data profiles.
        n_problems, n_solvers, n_runs, max_eval = merit_values.shape
        tolerances = np.logspace(-1, -10, 10)
        pdf_perf = backend_pdf.PdfPages(path_pdf_perf)
        pdf_data = backend_pdf.PdfPages(path_pdf_data)
        pdf_log_ratio = backend_pdf.PdfPages(path_pdf_log_ratio, False)
        for i_profile, tolerance in enumerate(tolerances):
            tolerance_str, tolerance_latex = _format_float_scientific_latex(tolerance)
            logger.info(f'Creating profiles for tolerance {tolerance_str}.')
            tolerance_label = f'($\\mathrm{{tol}} = {tolerance_latex}$)'

            work = np.full((n_problems, n_solvers, n_runs), np.nan)
            for i_problem in range(n_problems):
                for i_solver in range(n_solvers):
                    for i_run in range(n_runs):
                        if np.isfinite(merit_min[i_problem]):
                            threshold = max(tolerance * merit_init[i_problem] + (1.0 - tolerance) * merit_min[i_problem], merit_min[i_problem])
                        else:
                            threshold = -np.inf
                        if np.min(merit_values[i_problem, i_solver, i_run, :]) <= threshold:
                            work[i_problem, i_solver, i_run] = np.argmax(merit_values[i_problem, i_solver, i_run, :] <= threshold) + 1

            # Calculate the axes of the performance and data profiles.
            x_perf, y_perf, ratio_max_perf = _profile_axes(work, lambda i_problem, i_run: np.nanmin(work[i_problem, :, i_run], initial=np.inf))
            x_perf[np.isinf(x_perf)] = ratio_max_perf ** 2.0
            x_perf = np.vstack([np.ones((1, n_solvers)), x_perf])
            y_perf = np.vstack([np.zeros((1, n_solvers, n_runs)), y_perf])
            if n_problems > 0:
                x_perf = np.vstack([x_perf, np.full((1, n_solvers), ratio_max_perf ** 2.0)])
                y_perf = np.vstack([y_perf, y_perf[-1, np.newaxis, :, :]])
            x_data, y_data, ratio_max_data = _profile_axes(work, lambda i_problem, i_run: problem_dimensions[i_problem] + 1)
            x_data[np.isinf(x_data)] = 2.0 * ratio_max_data
            x_data = np.vstack([np.zeros((1, n_solvers)), x_data])
            y_data = np.vstack([np.zeros((1, n_solvers, n_runs)), y_data])
            if n_problems > 0:
                x_data = np.vstack([x_data, np.full((1, n_solvers), 2.0 * ratio_max_data)])
                y_data = np.vstack([y_data, y_data[-1, np.newaxis, :, :]])

            # Plot the performance profiles.
            fig, ax = _draw_profile(x_perf, y_perf, labels)
            ax.set_xscale('log', base=2)
            ax.set_xlim(1.0, ratio_max_perf ** 1.1)
            ax.set_xlabel('Performance ratio')
            ax.set_ylabel(f'Performance profiles {tolerance_label}')
            pdf_perf.savefig(fig, bbox_inches='tight')
            plt.close(fig)

            # Plot the data profiles.
            fig, ax = _draw_profile(x_data, y_data, labels)
            ax.set_xlim(0.0, 1.1 * ratio_max_data)
            ax.set_xlabel('Number of simplex gradients')
            ax.set_ylabel(f'Data profiles {tolerance_label}')
            pdf_data.savefig(fig, bbox_inches='tight')
            plt.close(fig)

            # Draw the log-ratio profiles.
            if n_solvers == 2:
                work_flat = np.reshape(np.swapaxes(work, 1, 2), (n_problems * n_runs, n_solvers))
                log_ratio = np.full(n_problems * n_runs, np.nan)
                log_ratio_finite = np.isfinite(work_flat[:, 0]) & np.isfinite(work_flat[:, 1])
                log_ratio[log_ratio_finite] = np.log2(work_flat[log_ratio_finite, 0] / work_flat[log_ratio_finite, 1])
                ratio_max = np.max(np.abs(log_ratio[log_ratio_finite]), initial=np.finfo(float).eps)
                log_ratio[np.isnan(work_flat[:, 0]) & np.isfinite(work_flat[:, 1])] = 2.0 * ratio_max
                log_ratio[np.isfinite(work_flat[:, 0]) & np.isnan(work_flat[:, 1])] = -2.0 * ratio_max
                log_ratio[np.isnan(work_flat[:, 0]) & np.isnan(work_flat[:, 1])] = 0.0
                log_ratio = np.sort(log_ratio)

                fig, ax = plt.subplots()
                ax.bar(np.arange(1, n_problems * n_runs + 1), log_ratio)
                ax.text((n_problems * n_runs + 1) / 2, -ratio_max, labels[0], horizontalalignment='center', verticalalignment='bottom')
                ax.text((n_problems * n_runs + 1) / 2, ratio_max, labels[1], horizontalalignment='center', verticalalignment='top')
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore', category=UserWarning)
                    ax.set_xlim(0.5, n_problems * n_runs + 0.5)
                ax.set_ylim(-1.1 * ratio_max, 1.1 * ratio_max)
                ax.set_xlabel('Problem')
                ax.set_ylabel(f'Log-ratio profile {tolerance_label}')
                pdf_log_ratio.savefig(fig, bbox_inches='tight')
                plt.close(fig)
        pdf_perf.close()
        pdf_data.close()
        pdf_log_ratio.close()
        logger.info(f'Results stored in {path_out}.')


def _solve_all(cutest_problem_names, cutest_problem_options, extra_problems, solvers, labels, feature, max_eval_factor, profile_options):
    problem_names = cutest_problem_names + extra_problems
    problem_options = [cutest_problem_options for _ in cutest_problem_names] + [{'name': f'EXTRA{i_problem + 1}'} for i_problem in range(len(extra_problems))]

    # Solve all problems.
    logger = get_logger(__name__)
    logger.info('Entering the parallel section.')
    results = Parallel(n_jobs=profile_options[ProfileOptionKey.N_JOBS])(_solve_one(problem_name, problem_option, solvers, labels, feature, max_eval_factor) for problem_name, problem_option in zip(problem_names, problem_options))
    logger.info('Leaving the parallel section.')
    if all(result is None for result in results):
        logger.critical('All problems failed to load.')
        _fun_values = []
        _maxcv_values = []
        fun_init = []
        maxcv_init = []
        n_eval = []
        problem_names = []
        problem_dimensions = []
    else:
        _fun_values, _maxcv_values, fun_init, maxcv_init, n_eval, problem_names, problem_dimensions = zip(*[result for result in results if result is not None])
    fun_init = np.array(fun_init)
    maxcv_init = np.array(maxcv_init)
    n_eval = np.array(n_eval)

    # Build the results.
    n_problems = len(problem_names)
    n_solvers = len(solvers)
    n_runs = feature.options[FeatureOptionKey.N_RUNS]
    max_eval = max_eval_factor * max(problem_dimensions) if len(problem_dimensions) > 0 else 1
    fun_values = np.full((n_problems, n_solvers, n_runs, max_eval), np.nan)
    maxcv_values = np.full((n_problems, n_solvers, n_runs, max_eval), np.nan)
    for i_problem, (fun_value, maxcv_value) in enumerate(zip(_fun_values, _maxcv_values)):
        max_eval = max_eval_factor * problem_dimensions[i_problem]
        fun_values[i_problem, ..., :max_eval] = fun_value
        maxcv_values[i_problem, ..., :max_eval] = maxcv_value
        if max_eval > 0:
            fun_values[i_problem, ..., max_eval:] = fun_values[i_problem, ..., max_eval - 1, np.newaxis]
            maxcv_values[i_problem, ..., max_eval:] = maxcv_values[i_problem, ..., max_eval - 1, np.newaxis]
    return fun_values, maxcv_values, fun_init, maxcv_init, n_eval, problem_names, problem_dimensions


@delayed
def _solve_one(problem_name, problem_options, solvers, labels, feature, max_eval_factor):
    # Load the problem and return if it cannot be loaded.
    if isinstance(problem_name, Problem):
        problem = problem_name
        problem_name = problem_options['name']
    else:
        try:
            problem = load_cutest_problem(problem_name, **problem_options)
        except ProblemError:
            return

    # Evaluate the functions at the initial point.
    fun_init = problem.fun(problem.x0)
    maxcv_init = problem.maxcv(problem.x0)

    # Solve the problem with each solver.
    n_solvers = len(solvers)
    n_runs = feature.options[FeatureOptionKey.N_RUNS]
    max_eval = max_eval_factor * problem.dimension
    n_eval = np.zeros((n_solvers, n_runs), dtype=int)
    fun_values = np.full((n_solvers, n_runs, max_eval), np.nan)
    maxcv_values = np.full((n_solvers, n_runs, max_eval), np.nan)
    logger = get_logger(__name__)
    for i_solver in range(n_solvers):
        for i_run in range(n_runs):
            logger.info(f'Solving {problem_name} with {labels[i_solver]} (run {i_run + 1}/{n_runs}).')
            featured_problem = FeaturedProblem(problem, feature, max_eval, i_run)
            sig = signature(solvers[i_solver])
            if len(sig.parameters) not in [2, 4, 8, 10]:
                raise ValueError(f'Unknown signature: {sig}.')
            with open(os.devnull, 'w') as devnull:
                with suppress(Exception), warnings.catch_warnings(), redirect_stdout(devnull), redirect_stderr(devnull):
                    warnings.filterwarnings('ignore')
                    if len(sig.parameters) == 2:
                        solvers[i_solver](featured_problem.fun, featured_problem.x0)
                    elif len(sig.parameters) == 4:
                        solvers[i_solver](featured_problem.fun, featured_problem.x0, featured_problem.lb, featured_problem.ub)
                    elif len(sig.parameters) == 8:
                        solvers[i_solver](featured_problem.fun, featured_problem.x0, featured_problem.lb, featured_problem.ub, featured_problem.a_ub, featured_problem.b_ub, featured_problem.a_eq, featured_problem.b_eq)
                    else:
                        solvers[i_solver](featured_problem.fun, featured_problem.x0, featured_problem.lb, featured_problem.ub, featured_problem.a_ub, featured_problem.b_ub, featured_problem.a_eq, featured_problem.b_eq, featured_problem.c_ub, featured_problem.c_eq)
            n_eval[i_solver, i_run] = featured_problem.n_eval
            fun_values[i_solver, i_run, :n_eval[i_solver, i_run]] = featured_problem.fun_history[:n_eval[i_solver, i_run]]
            maxcv_values[i_solver, i_run, :n_eval[i_solver, i_run]] = featured_problem.maxcv_history[:n_eval[i_solver, i_run]]
            if n_eval[i_solver, i_run] > 0:
                fun_values[i_solver, i_run, n_eval[i_solver, i_run]:] = fun_values[i_solver, i_run, n_eval[i_solver, i_run] - 1]
                maxcv_values[i_solver, i_run, n_eval[i_solver, i_run]:] = maxcv_values[i_solver, i_run, n_eval[i_solver, i_run] - 1]
    return fun_values, maxcv_values, fun_init, maxcv_init, n_eval, problem_name, problem.dimension


def _compute_merit_values(fun_values, maxcv_values):
    if isinstance(fun_values, np.ndarray) and isinstance(maxcv_values, np.ndarray):
        is_infeasible = maxcv_values >= 1e-6
        is_almost_feasible = (1e-12 < maxcv_values) & (maxcv_values < 1e-6)
        merit_values = np.nan_to_num(fun_values, nan=np.inf, posinf=np.inf, neginf=-np.inf)
        merit_values[is_infeasible] = np.inf
        merit_values[is_almost_feasible] += 1e8 * maxcv_values[is_almost_feasible]
        return merit_values
    elif maxcv_values <= 1e-12:
        return fun_values
    elif maxcv_values >= 1e-6:
        return np.inf
    else:
        return fun_values + 1e8 * maxcv_values


def _format_float_scientific_latex(x):
    raw = np.format_float_scientific(x, trim='-', exp_digits=0)
    match = re.compile(r'^(?P<coefficient>[0-9]+(\.[0-9]+)?)e(?P<exponent>(-)?[0-9]+)$').match(raw)
    if not match:
        raise ValueError(f'Cannot format {x} as scientific notation.')
    if match.group('coefficient') == '1':
        return raw, f'10^{{{match.group("exponent")}}}'
    return raw, f'{match.group("coefficient")} \\times 10^{{{match.group("exponent")}}}'


def _profile_axes(work, denominator):
    n_problems, n_solvers, n_runs = work.shape

    # Calculate the x-axis values.
    x = np.full((n_runs, n_problems, n_solvers), np.nan)
    for i_run in range(n_runs):
        for i_problem in range(n_problems):
            x[i_run, i_problem, :] = work[i_problem, :, i_run] / denominator(i_problem, i_run)
    ratio_max = np.nanmax(x, initial=np.finfo(float).eps)
    x[np.isnan(x)] = np.inf
    x = np.sort(x, 1)
    x = np.reshape(x, (n_problems * n_runs, n_solvers))
    sort_x = np.argsort(x, 0, 'stable')
    x = np.take_along_axis(x, sort_x, 0)

    # Calculate the y-axis values.
    y = np.full((n_problems * n_runs, n_solvers, n_runs), np.nan)
    for i_solver in range(n_solvers):
        for i_run in range(n_runs):
            if n_problems > 0:
                y[i_run * n_problems:(i_run + 1) * n_problems, i_solver, i_run] = np.linspace(1 / n_problems, 1.0, n_problems)
                y[:, i_solver, i_run] = np.take_along_axis(y[:, i_solver, i_run], sort_x[:, i_solver], 0)
            for i_problem in range(n_problems * n_runs):
                if np.isnan(y[i_problem, i_solver, i_run]):
                    y[i_problem, i_solver, i_run] = y[i_problem - 1, i_solver, i_run] if i_problem > 0 else 0.0
    return x, y, ratio_max


def _draw_profile(x, y, labels):
    n_solvers = x.shape[1]
    y_mean = np.mean(y, 2)
    y_min = np.min(y, 2)
    y_max = np.max(y, 2)
    fig, ax = plt.subplots()
    for i_solver in range(n_solvers):
        x_stairs = np.repeat(x[:, i_solver], 2)[1:]
        y_mean_stairs = np.repeat(y_mean[:, i_solver], 2)[:-1]
        y_min_stairs = np.repeat(y_min[:, i_solver], 2)[:-1]
        y_max_stairs = np.repeat(y_max[:, i_solver], 2)[:-1]
        ax.plot(x_stairs, y_mean_stairs, label=labels[i_solver])
        ax.fill_between(x_stairs, y_min_stairs, y_max_stairs, alpha=0.2)
    ax.yaxis.set_ticks_position('both')
    ax.yaxis.set_major_locator(MaxNLocator(5, prune='lower'))
    ax.yaxis.set_minor_locator(MaxNLocator(10))
    ax.tick_params(which='both', direction='in')
    ax.set_ylim(0.0, 1.0)
    ax.legend(loc='lower right')
    return fig, ax
