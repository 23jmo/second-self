"use client";

import { AnimatePresence, motion } from "motion/react";
import { useWizardState } from "@/hooks/useWizardState";
import WelcomeScreen from "./WelcomeScreen";
import NameInputScreen from "./NameInputScreen";
import BuildingScreen from "./BuildingScreen";
import ProfileScreen from "./ProfileScreen";
import CompleteScreen from "./CompleteScreen";


const fadeVariants = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
};

export default function Wizard() {
  const { state, next, back, setUser, setSession, setProfile } = useWizardState();

  const screens = [
    <WelcomeScreen key="welcome" onNext={next} onSession={setSession} />,
    <NameInputScreen key="name" onSubmit={setUser} onBack={back} />,
    <BuildingScreen
      key="building"
      name={state.name}
      role={state.role}
      email={state.email}
      sessionId={state.sessionId}
      onComplete={next}
      onProfile={setProfile}
    />,
    <ProfileScreen key="profile" name={state.name} role={state.role} profile={state.profile} onNext={next} onBack={back} />,
    <CompleteScreen key="complete" name={state.name} onBack={back} />,
  ];

  return (
    <div className="w-full flex items-center justify-center">
      <AnimatePresence mode="wait">
        <motion.div
          key={state.step}
          variants={fadeVariants}
          initial="initial"
          animate="animate"
          exit="exit"
          transition={{ duration: 0.5, ease: "easeInOut" }}
          className="w-full flex items-center justify-center"
        >
          {screens[state.step]}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
