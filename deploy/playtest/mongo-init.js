// The official image runs this only for a new volume, on a temporary localhost listener.
try {
    const fs = require("node:fs");
    const name = process.env.TWOWORLDS_PLAYTEST_MONGO_DATABASE;
    const adminPassword = fs.readFileSync("/run/secrets/mongo-admin-password", "utf8").trim();
    const appPassword = fs.readFileSync("/run/secrets/mongo-app-password", "utf8").trim();
    const randomHex = (value) => /^[0-9a-f]{64}$/.test(value) && new Set(value).size >= 12;
    if (!/^twoworlds_playtest_[a-z0-9_]{1,40}$/.test(name)
        || !randomHex(adminPassword) || !randomHex(appPassword) || adminPassword === appPassword) {
        throw Error();
    }
    db.getSiblingDB("admin").createUser({
        user: "playtest_admin",
        pwd: adminPassword,
        roles: [{role: "root", db: "admin"}],
        mechanisms: ["SCRAM-SHA-256"],
    });
    db.getSiblingDB(name).createUser({
        user: "playtest_app",
        pwd: appPassword,
        roles: [{role: "readWrite", db: name}],
        mechanisms: ["SCRAM-SHA-256"],
    });
} catch {
    print("Playtest MongoDB initialization failed");
    quit(1);
}
