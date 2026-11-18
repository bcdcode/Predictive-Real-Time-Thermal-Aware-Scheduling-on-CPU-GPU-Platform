
#define _GNU_SOURCE

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <sched.h>
#include <unistd.h>
#include <time.h>
#include <math.h>

static volatile double sink = 0.0;

int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <cpu> <seconds>\n", argv[0]);
        return 1;
    }

    int cpu = atoi(argv[1]);
    int seconds = atoi(argv[2]);

    if (cpu < 0 || seconds <= 0 || cpu >= CPU_SETSIZE) {
        fprintf(stderr, "Invalid CPU or duration\n");
        return 1;
    }

    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);

    if (sched_setaffinity(0, sizeof(set), &set) != 0) {
        perror("sched_setaffinity");
        return 1;
    }

    struct timespec start, now;
    clock_gettime(CLOCK_MONOTONIC, &start);

    uint64_t iterations = 0;
    double total = 0.0;

    while (1) {
        double x = 0.5;
        double y = 0.25;

        for (int i = 0; i < 1000000; i++) {
            x = fmod(x * 1.000001 + y, 1000.0);
            y = fmod(y * 0.999999 + x, 1000.0);
            total += x * y;

            if (total > 1.0e100 || total < -1.0e100)
                total = fmod(total, 1000.0);
        }

        sink = total;
        iterations++;

        clock_gettime(CLOCK_MONOTONIC, &now);

        double elapsed =
            (now.tv_sec - start.tv_sec) +
            (now.tv_nsec - start.tv_nsec) / 1e9;

        if (elapsed >= seconds)
            break;
    }

    fprintf(stderr,
            "CPU %d: %.1f seconds, %lu workload iterations, sink=%f\n",
            cpu, (double)seconds, (unsigned long)iterations,
            (double)sink);

    return isfinite(sink) ? 0 : 2;
}

