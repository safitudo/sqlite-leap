/* Mainline parse-only filter. Reads workload, prepares each stmt,
 * prints "OK\n" or "ERR\n" to stdout, summary to stderr.
 * For CREATE/INSERT/PRAGMA/BEGIN/COMMIT/UPDATE/DELETE/ALTER, also
 * step so subsequent stmts have schema.
 */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <sqlite3.h>

static char *slurp(const char *path, size_t *len_out) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = (char*)malloc((size_t)n + 1);
    if (fread(buf, 1, (size_t)n, f) != (size_t)n) { perror("read"); exit(2); }
    buf[n] = 0;
    fclose(f);
    *len_out = (size_t)n;
    return buf;
}

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
            size_t s = 0; while (buf[s]==' '||buf[s]=='\t'||buf[s]=='\n'||buf[s]=='\r') s++;
            size_t e = bi; while (e > s && (buf[e-1]==' '||buf[e-1]=='\t'||buf[e-1]=='\n'||buf[e-1]=='\r')) e--;
            if (e > s) {
                if (n == cap) { cap *= 2; arr = (char**)realloc(arr, cap*sizeof(char*)); }
                size_t L = e - s;
                char *p = (char*)malloc(L + 1);
                memcpy(p, buf + s, L); p[L] = 0;
                arr[n++] = p;
            }
            bi = 0;
        } else { buf[bi++] = c; }
    }
    free(buf);
    *out_n = n;
    return arr;
}

static int is_ddl_dml(const char *s) {
    while (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r') s++;
    char c = (char)toupper((unsigned char)*s);
    return c == 'C' || c == 'I' || c == 'P' || c == 'B' || c == 'A' ||
           c == 'D' || c == 'U' || c == 'R' || c == 'V' || c == 'T';
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s <workload.sql>\n", argv[0]); return 2; }
    size_t srclen; char *src = slurp(argv[1], &srclen);
    size_t n; char **stmts = split_stmts(src, &n);
    sqlite3 *db = NULL;
    if (sqlite3_open(":memory:", &db) != SQLITE_OK) return 2;
    long kept = 0, dropped = 0;
    for (size_t i = 0; i < n; i++) {
        sqlite3_stmt *st = NULL;
        int rc = sqlite3_prepare_v2(db, stmts[i], -1, &st, NULL);
        if (rc == SQLITE_OK) {
            if (is_ddl_dml(stmts[i])) {
                while (sqlite3_step(st) == SQLITE_ROW) {}
            }
            sqlite3_finalize(st);
            puts("OK"); kept++;
        } else {
            if (st) sqlite3_finalize(st);
            puts("ERR"); dropped++;
        }
    }
    fprintf(stderr, "kept=%ld dropped=%ld total=%zu\n", kept, dropped, n);
    sqlite3_close(db);
    return 0;
}
