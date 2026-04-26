/* In-process library-mode bench for libsqlite3.
 *
 * Mirrors src-rust/examples/lib_bench.rs: parses a SQL workload file
 * (statements separated by ';'), executes each in-process via
 * sqlite3_prepare_v2 -> sqlite3_step -> sqlite3_finalize, in a tight
 * loop, against the same in-memory database.
 *
 * Output (stdout): one line
 *   elapsed_seconds=<f> statements=<n> errors=<n> qps=<n>
 *
 * Usage:
 *   sqlite_lib_bench <workload.sql> [--time-setup] [--db <path>]
 *     default in-memory; --db FILE picks file-backed.
 *     --time-setup counts every statement (Lane 4 mode).
 *
 * Build:
 *   gcc -O3 sqlite_lib_bench.c -lsqlite3 -o sqlite_lib_bench
 */

#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sqlite3.h>

static char *slurp(const char *path, size_t *len_out) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = (char*)malloc((size_t)n + 1);
    if (!buf) { fprintf(stderr, "oom\n"); exit(2); }
    if (fread(buf, 1, (size_t)n, f) != (size_t)n) { perror("read"); exit(2); }
    buf[n] = 0;
    fclose(f);
    *len_out = (size_t)n;
    return buf;
}

/* Returns 1 if statement starts (case-insensitive) with `kw`. */
static int starts_with_ci(const char *s, const char *kw) {
    while (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r') s++;
    while (*kw) {
        char a = *s++; char b = *kw++;
        if (a >= 'a' && a <= 'z') a = (char)(a - 'a' + 'A');
        if (b >= 'a' && b <= 'z') b = (char)(b - 'a' + 'A');
        if (a != b) return 0;
    }
    return 1;
}

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

/* Splits buffer into ;-terminated statements (respecting single-quoted
 * strings). Returns array of malloc'd strings, count via *out_n. */
static char **split_stmts(const char *src, size_t *out_n) {
    size_t cap = 1024, n = 0;
    char **arr = (char**)malloc(cap * sizeof(char*));
    size_t buflen = strlen(src);
    char *buf = (char*)malloc(buflen + 1);
    size_t bi = 0;
    int in_str = 0;
    for (size_t i = 0; i < buflen; i++) {
        char c = src[i];
        if (c == '\'') in_str = !in_str;
        if (c == ';' && !in_str) {
            buf[bi] = 0;
            /* trim */
            size_t s = 0; while (buf[s] == ' '||buf[s]=='\t'||buf[s]=='\n'||buf[s]=='\r') s++;
            size_t e = bi; while (e > s && (buf[e-1]==' '||buf[e-1]=='\t'||buf[e-1]=='\n'||buf[e-1]=='\r')) e--;
            if (e > s) {
                if (n == cap) { cap *= 2; arr = (char**)realloc(arr, cap*sizeof(char*)); }
                size_t L = e - s;
                char *p = (char*)malloc(L + 1);
                memcpy(p, buf + s, L); p[L] = 0;
                arr[n++] = p;
            }
            bi = 0;
        } else {
            buf[bi++] = c;
        }
    }
    free(buf);
    *out_n = n;
    return arr;
}

/* Execute one statement via prepare/step/finalize. Returns 0 on ok, 1 err. */
static int run_one(sqlite3 *db, const char *sql) {
    sqlite3_stmt *st = NULL;
    int rc = sqlite3_prepare_v2(db, sql, -1, &st, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "prepare err: %s | sql=%.80s\n", sqlite3_errmsg(db), sql);
        if (st) sqlite3_finalize(st);
        return 1;
    }
    while ((rc = sqlite3_step(st)) == SQLITE_ROW) {
        /* Touch each column to mirror real consumer cost. */
        int nc = sqlite3_column_count(st);
        for (int i = 0; i < nc; i++) (void)sqlite3_column_int64(st, i);
    }
    if (rc != SQLITE_DONE) {
        fprintf(stderr, "step err: %s\n", sqlite3_errmsg(db));
        sqlite3_finalize(st);
        return 1;
    }
    sqlite3_finalize(st);
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s <workload.sql> [--time-setup] [--db PATH]\n", argv[0]); return 2; }
    const char *path = argv[1];
    int time_setup = 0;
    const char *db_path = ":memory:";
    for (int i = 2; i < argc; i++) {
        if (strcmp(argv[i], "--time-setup") == 0) time_setup = 1;
        else if (strcmp(argv[i], "--db") == 0 && i + 1 < argc) { db_path = argv[++i]; }
    }

    size_t srclen;
    char *src = slurp(path, &srclen);
    size_t n;
    char **stmts = split_stmts(src, &n);

    sqlite3 *db = NULL;
    if (sqlite3_open(db_path, &db) != SQLITE_OK) {
        fprintf(stderr, "open: %s\n", sqlite3_errmsg(db));
        return 2;
    }

    long counted = 0, errors = 0;
    double t0;

    if (!time_setup) {
        /* Untimed phase: PRAGMA / CREATE / BEGIN / INSERT / COMMIT.
         * Timed phase starts at first SELECT. */
        size_t first_sel = n;
        for (size_t i = 0; i < n; i++) if (starts_with_ci(stmts[i], "SELECT")) { first_sel = i; break; }
        for (size_t i = 0; i < first_sel; i++) {
            if (run_one(db, stmts[i]) != 0) errors++;
        }
        t0 = now_s();
        for (size_t i = first_sel; i < n; i++) {
            if (run_one(db, stmts[i]) == 0) counted++; else errors++;
        }
    } else {
        t0 = now_s();
        for (size_t i = 0; i < n; i++) {
            if (run_one(db, stmts[i]) == 0) counted++; else errors++;
        }
    }
    double elapsed = now_s() - t0;

    sqlite3_close(db);
    for (size_t i = 0; i < n; i++) free(stmts[i]);
    free(stmts);
    free(src);

    long qps = elapsed > 0 ? (long)((double)counted / elapsed) : 0;
    printf("elapsed_seconds=%.6f statements=%ld errors=%ld qps=%ld\n",
           elapsed, counted, errors, qps);
    return 0;
}
