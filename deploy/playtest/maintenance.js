// Run inside the dedicated Mongo container, with the application already stopped.
try {
    const fs = require("node:fs");
    const name = process.env.TWOWORLDS_PLAYTEST_MONGO_DATABASE;
    const confirmation = process.env.PLAYTEST_CONFIRM || "";
    if (!/^twoworlds_playtest_[a-z0-9_]{1,40}$/.test(name)
        || !["", "REVOKE:" + name, "DROP:" + name].includes(confirmation)) {
        throw Error();
    }

    const uri = "mongodb://127.0.0.1:27017/?directConnection=true&serverSelectionTimeoutMS=3000";
    const connection = new Mongo(uri);
    const authenticate = (database, role) => {
        const password = fs.readFileSync("/run/secrets/mongo-" + role + "-password", "utf8").trim();
        if (!/^[0-9a-f]{64}$/.test(password)) throw Error();
        database.auth({user: "playtest_" + role, pwd: password, mechanism: "SCRAM-SHA-256"});
        const status = database.runCommand({connectionStatus: 1});
        if (!status.ok || !status.authInfo.authenticatedUsers.some((user) =>
            user.user === "playtest_" + role && user.db === database.getName())) throw Error();
    };

    const target = connection.getDB(name);
    authenticate(target, "app");
    const aliases = target.accounts.distinct("email").sort();
    const testEmail = /^[a-z][a-z0-9-]{0,31}@playtest\.invalid$/;
    if (aliases.some((email) => !testEmail.test(email))
        || target.accounts.countDocuments() !== aliases.length) throw Error();
    const active = () => target.accounts.countDocuments({"sessions.0": {$exists: true}});
    let result = "dry-run";
    if (confirmation === "REVOKE:" + name) {
        const updated = target.accounts.updateMany(
            {"sessions.0": {$exists: true}}, {$set: {sessions: []}, $inc: {version: 1}},
        );
        if (!updated.acknowledged || active() !== 0) throw Error();
        result = "revoked";
    } else if (confirmation === "DROP:" + name) {
        if (active() !== 0) throw Error();
        const admin = new Mongo(uri);
        authenticate(admin.getDB("admin"), "admin");
        if (!admin.getDB(name).dropDatabase().ok || target.getCollectionNames().length !== 0) throw Error();
        result = "dropped";
    }
    print(JSON.stringify({result, database: name, aliases, accountsWithSessions: active()}));
} catch {
    print("Playtest maintenance refused or failed. Check the isolated database, aliases and confirmation.");
    quit(1);
}
