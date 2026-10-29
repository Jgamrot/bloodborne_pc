/* Local trophy history for the native port. Never writes to the game dump or PSN. */
#include "runtime.h"
#include "gpu/bbgpu.h"
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

enum { TROPHY_LIMIT = 128 };
static pthread_mutex_t trophy_lock = PTHREAD_MUTEX_INITIALIZER;
static int64_t unlocked[TROPHY_LIMIT];
static char trophy_path[1024];

void runtime_trophy_configure(void) {
    pthread_mutex_lock(&trophy_lock);
    memset(unlocked, 0, sizeof(unlocked));
    int length = snprintf(trophy_path, sizeof(trophy_path), "%s/trophies.txt",
                          runtime_file_user_dir());
    if (length < 0 || (size_t)length >= sizeof(trophy_path)) {
        trophy_path[0] = 0;
    }
    FILE *file = trophy_path[0] ? fopen(trophy_path, "r") : NULL;
    if (file) {
        char line[96];
        while (fgets(line, sizeof(line), file)) {
            int id;
            long long when;
            char extra;
            if (sscanf(line, "%d %lld %c", &id, &when, &extra) == 2 &&
                id >= 0 && id < TROPHY_LIMIT) {
                unlocked[id] = when > 0 ? when : 1;
            }
        }
        fclose(file);
    }
    bbgpu_trophy_load(unlocked, TROPHY_LIMIT);
    pthread_mutex_unlock(&trophy_lock);
}

int runtime_trophy_unlock(int id) {
    if (id < 0 || id >= TROPHY_LIMIT) return -1;
    pthread_mutex_lock(&trophy_lock);
    if (unlocked[id]) {
        pthread_mutex_unlock(&trophy_lock);
        printf("Runtime: local trophy %d already unlocked\n", id);
        return 0;
    }
    const int64_t now = (int64_t)time(NULL);
    unlocked[id] = now;
    FILE *file = trophy_path[0] ? fopen(trophy_path, "a") : NULL;
    if (file) {
        fprintf(file, "%d %lld\n", id, (long long)now);
        if (fclose(file) != 0) {
            fprintf(stderr, "Runtime: could not save trophy %d\n", id);
        }
    } else {
        fprintf(stderr, "Runtime: could not open local trophy history for trophy %d\n", id);
    }
    printf("Runtime: local trophy %d unlocked\n", id);
    bbgpu_trophy_unlocked(id, now);
    pthread_mutex_unlock(&trophy_lock);
    return 1;
}
